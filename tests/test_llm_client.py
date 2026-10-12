from core.schemas import Plan
from core.llm_client import get_llm_client


def test_mock_client_returns_valid_plan():
    client = get_llm_client()
    result = client.structured_call(
        system_prompt="You are a task planner.",
        user_prompt="Goal: enter an invoice into the system.",
        schema=Plan,
    )
    assert isinstance(result, Plan)
    assert isinstance(result.steps, list)
    assert isinstance(result.success_criteria, list)