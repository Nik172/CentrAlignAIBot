"""
The autonomy core. Every loop iteration, this asks: given everything that
has happened so far, what is the single next best action? It is NOT a
pre-committed script executor — it re-reasons from fresh state every step,
which is what lets it react to failures, missing data, and policy
thresholds instead of blindly running step N+1.
"""
import json
from core.schemas import Decision
from core.llm_client import LLMClient
from core.tools.base import Tool


class DecisionEngine:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def decide(self, goal: str, plan_steps: list[str], tools: list[Tool],
               working_memory: dict, history: list[dict], company_context: str,
               retry_context: dict) -> Decision:
        tool_specs = [t.to_prompt_spec() for t in tools]
        system_prompt = (
            "You are the decision-making core of an autonomous AI worker operating inside a "
            "company. Given the goal, draft plan, available tools, what has happened so far, "
            "and what you currently know, decide the SINGLE next best action.\n\n"
            "Rules:\n"
            "- type=act: call exactly one tool via tool_call {tool_name, params_json}. "
            "params_json MUST be a valid JSON string (not an object), e.g. "
            '\'{"action": "find", "company": "Company X"}\'.\n'
            "- type=ask_human: use ONLY when you cannot safely proceed without human input "
            "(missing/ambiguous data, a policy threshold mentioned in company_context, or "
            "repeated failures). Put your question in question_for_human.\n"
            "- type=declare_done: use only when you believe the goal has likely been achieved "
            "and the system should now independently verify it.\n"
            "- Never fabricate data. Use working_memory and recent_observations as ground truth.\n"
            "- If a past action failed, do not blindly repeat the exact same action — adapt, or "
            "ask_human if you're stuck.\n"
            "- Respect any policy rules present in company_context (e.g. approval thresholds)."
        )
        user_prompt = json.dumps({
            "goal": goal,
            "company_context": company_context,
            "draft_plan_steps": plan_steps,
            "available_tools": tool_specs,
            "working_memory": working_memory,
            "recent_observations": history[-5:],
            "retry_context": retry_context,
        }, default=str, indent=2)
        return self.llm.structured_call(system_prompt, user_prompt, Decision)