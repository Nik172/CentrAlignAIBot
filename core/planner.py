"""
Decomposes a goal into a draft step sequence via LLM. Success criteria are
NOT LLM-generated here — they require exact knowledge of the internal
system's API schema (endpoint paths, field names), which the LLM has no
reliable way to know. Those come from the task config instead (see
Orchestrator.run). The LLM's job is purely the reasoning/decomposition,
which is the genuinely autonomous part worth demonstrating.
"""
import json
from core.schemas import Plan
from core.llm_client import LLMClient
from core.tools.base import Tool


class Planner:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def plan(self, goal: str, tools: list[Tool], company_context: str) -> Plan:
        tool_specs = [t.to_prompt_spec() for t in tools]
        system_prompt = (
            "You are the planning module of an autonomous AI worker. Given a goal and the "
            "tools available, produce a short draft sequence of steps describing your approach. "
            "This is a hypothesis, not a rigid script — the executor may deviate as it learns more. "
            "Leave success_criteria as an empty list; that is handled elsewhere."
        )
        user_prompt = json.dumps({
            "goal": goal,
            "available_tools": tool_specs,
            "company_context": company_context,
        }, indent=2)
        return self.llm.structured_call(system_prompt, user_prompt, Plan)