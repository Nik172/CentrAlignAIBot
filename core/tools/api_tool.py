"""
Generic tool for calling any internal company backend over HTTP.
Deliberately generic (method/path/query/body) rather than invoice-specific,
so the same tool gets reused unmodified for ticket systems, onboarding
APIs, etc. — this is one of the pieces that makes the generalization
claim real rather than aspirational.
"""
import httpx
from datetime import datetime, timezone

from core.schemas import Observation
from core.tools.base import Tool


class ApiTool(Tool):
    name = "internal_api"
    description = (
        "Calls the company's internal system over HTTP. Supports GET/POST/PUT/DELETE "
        "against configured endpoints. Use this to create, query, or update records "
        "in the internal system."
    )
    input_schema = {
        "method": "HTTP method: GET | POST | PUT | DELETE",
        "path": "endpoint path, e.g. '/invoices'",
        "query": "optional dict of query parameters",
        "json_body": "optional dict to send as JSON body (for POST/PUT)",
    }

    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 3.0):
        self.base_url = base_url
        self.timeout = timeout
        # Timeout is set once here, at the client level. We deliberately do NOT
        # pass timeout= again per-request — httpx.Client already applies it to
        # every call, and passing it again breaks compatibility with test doubles
        # like Starlette's TestClient (which has no real socket to time out on).
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def execute(self, params: dict) -> Observation:
        method = params.get("method", "GET").upper()
        path = params.get("path", "/")
        query = params.get("query") or {}
        json_body = params.get("json_body")

        try:
            response = self.client.request(method, path, params=query, json=json_body)
        except httpx.TimeoutException:
            return self._fail(f"{method} {path} timed out.", error_type="timeout")
        except httpx.ConnectError:
            return self._fail(f"Could not connect to {self.base_url}{path}.", error_type="connection_error")

        if response.status_code >= 500:
            return self._fail(
                f"{method} {path} returned server error {response.status_code}.",
                error_type="server_error",
            )
        if response.status_code >= 400:
            return self._fail(
                f"{method} {path} returned client error {response.status_code}: {response.text}",
                error_type="http_error",
            )

        try:
            data = response.json()
        except ValueError:
            data = {"raw_text": response.text}

        return Observation(
            tool_name=self.name,
            success=True,
            raw_output=data,
            structured_data=data if isinstance(data, dict) else {"result": data},
            timestamp=self._now(),
        )

    def _fail(self, message: str, error_type: str) -> Observation:
        return Observation(
            tool_name=self.name,
            success=False,
            raw_output=None,
            structured_data={},
            error_type=error_type,
            error_message=message,
            timestamp=self._now(),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()