"""
CLI human-in-the-loop interface. Blocks execution until the user responds.
Kept intentionally simple (stdin) for the prototype; swapping this for a
web form or Slack message later requires no changes to the orchestrator,
since it only depends on the `ask(question, context) -> HumanResponse`
interface.
"""
import json
from core.schemas import HumanResponse


class CLIHumanInterface:
    def ask(self, question: str, context: dict | None = None) -> HumanResponse:
        print("\n" + "=" * 60)
        print("🧑 HUMAN INPUT NEEDED")
        print(question)
        if context:
            print(f"(relevant context: {json.dumps(context, default=str)[:300]})")
        print("=" * 60)
        answer = input("Your response: ")
        return HumanResponse(answer=answer)