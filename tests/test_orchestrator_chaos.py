"""
Integration tests for the orchestrator's reliability behavior: chaos
recovery and circuit-breaker escalation. Uses a deterministic scripted
LLM client (no network/API key dependency) so these tests are fast,
reproducible, and not subject to live-model flakiness — we're testing
OUR control-flow logic, not the LLM's reasoning quality.
"""
import json
import pytest
from fastapi.testclient import TestClient

from core.schemas import Plan, Decision, DecisionType, ToolCall, HumanResponse
from core.orchestrator import Orchestrator
from core.tools.file_reader_tool import FileReaderTool
from core.tools.api_tool import ApiTool
from core.llm_client import LLMClient
from mock_envs.internal_system_app.main import app
from mock_envs.internal_system_app import db
from mock_envs.shared.chaos import chaos_manager


class ScriptedLLMClient(LLMClient):
    """Returns a pre-scripted sequence of Decisions. Clamps to the last
    entry once exhausted, so tests don't need exact step-count math."""
    def __init__(self, plan: Plan, decisions: list[Decision]):
        self.plan = plan
        self.decisions = decisions
        self._i = 0

    def structured_call(self, system_prompt, user_prompt, schema):
        if schema is Plan:
            return self.plan
        if schema is Decision:
            idx = min(self._i, len(self.decisions) - 1)
            d = self.decisions[idx]
            self._i += 1
            return d
        raise ValueError(f"ScriptedLLMClient got unexpected schema: {schema}")


class _NoOpHumanInterface:
    def ask(self, question, context=None):
        raise AssertionError(f"Unexpected human escalation: {question}")


class _RecordingHumanInterface:
    def __init__(self):
        self.calls: list[str] = []

    def ask(self, question, context=None):
        self.calls.append(question)
        return HumanResponse(answer="Skip this one for now.")


@pytest.fixture(autouse=True)
def clean_state():
    db.reset_db()
    chaos_manager.clear()
    yield
    db.reset_db()
    chaos_manager.clear()


def _tool_call(name, params: dict) -> ToolCall:
    return ToolCall(tool_name=name, params_json=json.dumps(params))


def _make_tools():
    client = TestClient(app, base_url="http://test")
    api_tool = ApiTool(base_url="http://test", client=client)
    file_tool = FileReaderTool(base_dir="tasks/sample_data/invoices")
    return api_tool, file_tool


def test_orchestrator_recovers_from_transient_chaos_and_verifies():
    chaos_manager.set_rule(target="/invoices", mode="error_500", times=1)
    api_tool, file_tool = _make_tools()

    plan = Plan(steps=["find", "extract", "submit", "verify"], reasoning="test plan")
    decisions = [
        Decision(type=DecisionType.ACT, reasoning="find file",
                  tool_call=_tool_call("file_reader", {"action": "find", "company": "Company X"})),
        Decision(type=DecisionType.ACT, reasoning="extract fields",
                  tool_call=_tool_call("file_reader", {
                      "action": "extract", "path": "tasks/sample_data/invoices/company_x_clean.txt"})),
        Decision(type=DecisionType.ACT, reasoning="submit invoice (hits chaos failure)",
                  tool_call=_tool_call("internal_api", {
                      "method": "POST", "path": "/invoices",
                      "json_body": {"company": "Company X", "amount": 42000.0, "due_date": "2025-11-15"}})),
        Decision(type=DecisionType.ACT, reasoning="retry submit after transient failure",
                  tool_call=_tool_call("internal_api", {
                      "method": "POST", "path": "/invoices",
                      "json_body": {"company": "Company X", "amount": 42000.0, "due_date": "2025-11-15"}})),
        Decision(type=DecisionType.DECLARE_DONE, reasoning="done, verify now"),
    ]
    llm = ScriptedLLMClient(plan, decisions)

    task_config = {
        "task_id": "test_chaos_recovery",
        "goal": "Enter Company X's invoice into the internal system.",
        "max_steps": 10,
        "max_retries_per_action": 2,
        "success_criteria": [
            {"id": "c1", "description": "amount matches", "check_type": "api_query",
             "check_target": "/invoices", "expected_field": "amount", "expected_source": "amount"},
            {"id": "c2", "description": "due date matches", "check_type": "api_query",
             "check_target": "/invoices", "expected_field": "due_date", "expected_source": "due_date"},
        ],
    }

    orchestrator = Orchestrator(
        task_config=task_config, tools={"file_reader": file_tool, "internal_api": api_tool},
        api_tool_for_verification=api_tool, llm=llm, human_interface=_NoOpHumanInterface(),
        company_context="", log_dir="logs",
    )

    summary = orchestrator.run()

    assert summary.final_status.value == "verified"
    log_content = open(orchestrator.log_path).read()
    assert "RETRYING" in log_content
    assert "ERROR_CLASSIFIED" in log_content


def test_circuit_breaker_trips_and_forces_escalation():
    # Every attempt fails (times=5, never exhausted during this test).
    chaos_manager.set_rule(target="/invoices", mode="error_500", times=5)
    api_tool, file_tool = _make_tools()

    plan = Plan(steps=["find", "extract", "submit"], reasoning="test plan")
    submit_decision = Decision(type=DecisionType.ACT, reasoning="submit invoice",
                                tool_call=_tool_call("internal_api", {
                                    "method": "POST", "path": "/invoices",
                                    "json_body": {"company": "Company X", "amount": 42000.0, "due_date": "2025-11-15"}}))
    decisions = [
        Decision(type=DecisionType.ACT, reasoning="find file",
                  tool_call=_tool_call("file_reader", {"action": "find", "company": "Company X"})),
        Decision(type=DecisionType.ACT, reasoning="extract fields",
                  tool_call=_tool_call("file_reader", {
                      "action": "extract", "path": "tasks/sample_data/invoices/company_x_clean.txt"})),
        submit_decision, submit_decision, submit_decision,  # 3 identical failing attempts
        Decision(type=DecisionType.DECLARE_DONE, reasoning="give up, declare done"),
    ]
    llm = ScriptedLLMClient(plan, decisions)
    human = _RecordingHumanInterface()

    task_config = {
        "task_id": "test_circuit_breaker",
        "goal": "Enter Company X's invoice into the internal system.",
        "max_steps": 10,
        "max_retries_per_action": 2,
        "success_criteria": [
            {"id": "c1", "description": "amount matches", "check_type": "api_query",
             "check_target": "/invoices", "expected_field": "amount", "expected_source": "amount"},
        ],
    }

    orchestrator = Orchestrator(
        task_config=task_config, tools={"file_reader": file_tool, "internal_api": api_tool},
        api_tool_for_verification=api_tool, llm=llm, human_interface=human,
        company_context="", log_dir="logs",
    )

    summary = orchestrator.run()

    assert len(human.calls) >= 1
    log_content = open(orchestrator.log_path).read()
    assert "CIRCUIT_BREAKER_TRIPPED" in log_content
    assert "CIRCUIT_BREAKER_FORCED_ESCALATION" in log_content
    assert summary.final_status.value == "failed"