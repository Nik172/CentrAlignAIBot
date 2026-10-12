"""
The control loop: PLAN -> (ACT -> OBSERVE -> DECIDE)* -> VERIFY -> SUMMARY,
with ASK_HUMAN as an escape hatch at any point, and a circuit breaker that
forces escalation if the same action keeps failing. Plain Python loop, not
a framework DAG — needs to re-reason every step from fresh state.
"""
import json
import time
from pathlib import Path
from datetime import datetime, timezone

from core.schemas import (
    Decision, DecisionType, Observation, ErrorCategory, SuccessCriterion,
    Verdict, VerdictStatus, TaskSummary,
)
from core.planner import Planner
from core.decision_engine import DecisionEngine
from core.error_classifier import ErrorClassifier
from core.verifier import Verifier


class Orchestrator:
    def __init__(self, task_config: dict, tools: dict, api_tool_for_verification,
                 llm, human_interface, company_context: str = "", log_dir: str = "logs"):
        self.config = task_config
        self.tools = tools
        self.planner = Planner(llm)
        self.decision_engine = DecisionEngine(llm)
        self.error_classifier = ErrorClassifier()
        self.verifier = Verifier(api_tool_for_verification)
        self.human_interface = human_interface
        self.company_context = company_context

        self.working_memory: dict = {}
        self.history: list[dict] = []
        self.retry_counts: dict[str, int] = {}

        self.max_steps = task_config.get("max_steps", 12)
        self.max_retries_per_action = task_config.get("max_retries_per_action", 2)

        Path(log_dir).mkdir(parents=True, exist_ok=True)
        self.log_path = Path(log_dir) / f"{task_config['task_id']}_{int(time.time())}.jsonl"

    def _log(self, event_type: str, data: dict):
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event_type, **data}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        print(f"[{event_type}] {json.dumps(data, default=str)[:300]}")

    def run(self) -> TaskSummary:
        goal = self.config["goal"]
        criteria = [SuccessCriterion(**c) for c in self.config["success_criteria"]]

        self._log("TASK_START", {"goal": goal})

        plan = self._safe_plan(goal)
        plan.success_criteria = criteria
        self._log("PLAN_CREATED", {"steps": plan.steps, "reasoning": plan.reasoning})

        step_count = 0
        while step_count < self.max_steps:
            step_count += 1

            # Circuit breaker: if an action has failed past the retry limit,
            # force escalation instead of letting the decision engine keep
            # trying. Hard safety net — does not depend on the LLM choosing
            # to ask for help.
            if self.working_memory.get("circuit_breaker_tripped"):
                self._log("CIRCUIT_BREAKER_FORCED_ESCALATION", {
                    "reason": self.working_memory.get("last_error"),
                })
                response = self.human_interface.ask(
                    "I've repeatedly failed the same action and am stopping to avoid looping "
                    f"indefinitely. Last error: {self.working_memory.get('last_error')}. "
                    "How should I proceed?",
                    context=self.working_memory,
                )
                self.working_memory["last_human_answer"] = response.answer
                self.working_memory["circuit_breaker_tripped"] = False
                self._log("HUMAN_RESPONSE", {
                    "question": "(circuit breaker escalation)", "answer": response.answer,
                })
                continue

            decision = self._safe_decide(goal, plan)
            self._log("DECISION", {"step": step_count, "type": decision.type, "reasoning": decision.reasoning})

            if decision.type == DecisionType.ACT:
                self._act(decision)

            elif decision.type == DecisionType.ASK_HUMAN:
                question = decision.question_for_human or "The agent needs input to proceed."
                response = self.human_interface.ask(question, context=self.working_memory)
                self.working_memory["last_human_answer"] = response.answer
                self._log("HUMAN_RESPONSE", {"question": question, "answer": response.answer})

            elif decision.type == DecisionType.REPLAN:
                plan = self._safe_plan(goal)
                plan.success_criteria = criteria
                self._log("REPLAN", {"steps": plan.steps})

            elif decision.type == DecisionType.DECLARE_DONE:
                verdict = self.verifier.verify(criteria, self.working_memory)
                self._log("VERIFICATION", {"status": verdict.status, "summary": verdict.summary})
                if verdict.status == VerdictStatus.VERIFIED:
                    return self._finish(goal, verdict)
                self.working_memory["verification_feedback"] = verdict.summary
                self._log("VERIFICATION_NOT_PASSED_CONTINUING", {})

        final_verdict = self.verifier.verify(criteria, self.working_memory)
        self._log("MAX_STEPS_REACHED", {"final_status": final_verdict.status})
        return self._finish(goal, final_verdict, exhausted=True)

    # -- safety wrappers so a flaky LLM call never crashes a live demo --------

    def _safe_plan(self, goal: str):
        try:
            return self.planner.plan(goal, list(self.tools.values()), self.company_context)
        except Exception as e:
            self._log("PLANNER_ERROR", {"error": str(e)})
            from core.schemas import Plan
            return Plan(steps=["(planning failed — proceeding reactively)"], reasoning=str(e))

    def _safe_decide(self, goal: str, plan) -> Decision:
        try:
            decision = self.decision_engine.decide(
                goal=goal, plan_steps=plan.steps, tools=list(self.tools.values()),
                working_memory=self.working_memory, history=self.history,
                company_context=self.company_context, retry_context=self.retry_counts,
            )
        except Exception as e:
            self._log("DECISION_ENGINE_ERROR", {"error": str(e)})
            return Decision(type=DecisionType.ASK_HUMAN, reasoning=f"Internal reasoning error: {e}",
                             question_for_human="I hit an internal error while deciding what to do next. "
                                                "Please advise how to proceed.")

        if decision.type == DecisionType.ACT and decision.tool_call is None:
            self._log("INVALID_DECISION", {"reason": "type=act but tool_call is None", "raw": decision.reasoning})
            return Decision(type=DecisionType.ASK_HUMAN,
                             reasoning="Decision engine returned an incomplete action.",
                             question_for_human="I wasn't able to determine a valid next action. "
                                                "Could you clarify what I should do next?")
        if decision.type == DecisionType.ASK_HUMAN and not decision.question_for_human:
            decision.question_for_human = "I need guidance to proceed, but no specific question was generated."

        return decision

    # -- action execution -------------------------------------------------

    def _act(self, decision: Decision):
        tool_call = decision.tool_call
        try:
            params = json.loads(tool_call.params_json) if tool_call.params_json else {}
        except json.JSONDecodeError as e:
            self._log("PARAM_PARSE_ERROR", {"raw": tool_call.params_json, "error": str(e)})
            self.working_memory["last_error"] = f"Malformed tool parameters: {e}"
            self.working_memory["last_error_category"] = ErrorCategory.AMBIGUOUS
            return

        tool = self.tools.get(tool_call.tool_name)
        if tool is None:
            obs = Observation(tool_name=tool_call.tool_name, success=False, error_type="unknown_tool",
                               error_message=f"No such tool: {tool_call.tool_name}", timestamp=self._now())
        else:
            obs = tool.execute(params)

        self._log("OBSERVATION", {
            "tool": tool_call.tool_name, "params": params, "success": obs.success,
            "error_type": obs.error_type, "structured_data": obs.structured_data,
        })
        self.history.append({
            "tool": tool_call.tool_name, "params": params, "success": obs.success,
            "error_type": obs.error_type, "structured_data": obs.structured_data,
            "error_message": obs.error_message,
        })

        if isinstance(obs.structured_data, dict) and obs.structured_data:
            self.working_memory.update(obs.structured_data)

        if obs.success:
            # Capture inputs the agent used, not just outputs — lets the
            # Verifier later look up "which company/customer/record" to
            # re-check, generically, regardless of task domain.
            if params.get("json_body"):
                self.working_memory.update(params["json_body"])
            if params.get("query"):
                self.working_memory.update(params["query"])
        else:
            self._handle_failure(decision, obs, params)

    def _handle_failure(self, decision: Decision, obs: Observation, params: dict):
        key = f"{decision.tool_call.tool_name}:{json.dumps(params, default=str, sort_keys=True)}"
        self.retry_counts[key] = self.retry_counts.get(key, 0) + 1

        classification = self.error_classifier.classify(obs)
        self._log("ERROR_CLASSIFIED", {"error_type": obs.error_type, "category": classification.category,
                                        "reasoning": classification.reasoning})

        self.working_memory["last_error"] = obs.error_message
        self.working_memory["last_error_category"] = classification.category

        if classification.category == ErrorCategory.TRANSIENT and self.retry_counts[key] <= self.max_retries_per_action:
            wait = 0.5 * (2 ** (self.retry_counts[key] - 1))
            self._log("RETRYING", {"attempt": self.retry_counts[key], "wait_seconds": wait})
            time.sleep(wait)
        elif self.retry_counts[key] > self.max_retries_per_action:
            self.working_memory["circuit_breaker_tripped"] = True
            self._log("CIRCUIT_BREAKER_TRIPPED", {"key": key})

    def _finish(self, goal: str, verdict: Verdict, exhausted: bool = False) -> TaskSummary:
        summary_text = (
            f"Goal: {goal}\nFinal status: {verdict.status}\n{verdict.summary}"
            + ("\n(Stopped after reaching max steps.)" if exhausted else "")
        )
        self._log("TASK_END", {"status": verdict.status, "summary": summary_text})
        return TaskSummary(task_id=self.config["task_id"], goal=goal, final_status=verdict.status,
                            summary_text=summary_text, evidence=[str(self.log_path)])

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()