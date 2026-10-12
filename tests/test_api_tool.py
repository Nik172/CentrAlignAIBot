import httpx
import pytest
from fastapi.testclient import TestClient

from mock_envs.internal_system_app.main import app
from mock_envs.internal_system_app import db
from mock_envs.shared.chaos import chaos_manager
from core.tools.api_tool import ApiTool


@pytest.fixture(autouse=True)
def clean_state():
    db.reset_db()
    chaos_manager.clear()
    yield
    db.reset_db()
    chaos_manager.clear()


def make_tool(timeout: float = 3.0) -> ApiTool:
    client = TestClient(app, base_url="http://test")
    return ApiTool(base_url="http://test", client=client, timeout=timeout)


def test_create_and_query_invoice():
    tool = make_tool()
    obs = tool.execute({
        "method": "POST", "path": "/invoices",
        "json_body": {"company": "Company X", "invoice_number": "INV-1001", "amount": 42000, "due_date": "2025-11-15"},
    })
    assert obs.success

    obs2 = tool.execute({"method": "GET", "path": "/invoices", "query": {"company": "Company X"}})
    assert obs2.success
    assert obs2.structured_data["result"][0]["amount"] == 42000


class _AlwaysTimesOutClient:
    """Fake client that simulates a real network timeout exception.

    We use this instead of racing TestClient against a server-side sleep,
    because TestClient runs the ASGI app in-process with no real socket —
    there's nothing for a client-side timeout to actually abort. This test
    instead verifies ApiTool's own exception-handling/classification logic
    directly and deterministically.

    The real client-side timeout (sleep vs. timeout race) is demonstrated
    live against the actual running uvicorn server — see README demo steps.
    """
    def request(self, method, url, params=None, json=None):
        raise httpx.TimeoutException("Simulated timeout")


def test_timeout_is_classified_correctly():
    tool = ApiTool(base_url="http://test", client=_AlwaysTimesOutClient())
    obs = tool.execute({"method": "GET", "path": "/invoices"})
    assert not obs.success
    assert obs.error_type == "timeout"


def test_error_500_chaos():
    chaos_manager.set_rule(target="/invoices", mode="error_500", times=1)
    tool = make_tool()
    obs = tool.execute({"method": "GET", "path": "/invoices"})
    assert not obs.success
    assert obs.error_type == "server_error"


def test_missing_field_chaos():
    tool = make_tool()
    tool.execute({
        "method": "POST", "path": "/invoices",
        "json_body": {"company": "Company X", "amount": 42000, "due_date": "2025-11-15"},
    })
    chaos_manager.set_rule(target="/invoices", mode="missing_field", field_name="due_date", times=1)
    obs = tool.execute({"method": "GET", "path": "/invoices", "query": {"company": "Company X"}})
    assert obs.success
    assert "due_date" not in obs.structured_data["result"][0]