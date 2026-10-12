"""
Finds, reads, and extracts structured fields from the company's document
store. Extraction uses deterministic regex rather than an LLM call — since
we control the mock documents, this keeps "does extraction fail" decoupled
from "is the LLM having a bad day", which makes failure-handling demos
meaningful rather than accidental.
"""
import re
from pathlib import Path
from datetime import datetime, timezone

from core.schemas import Observation
from core.tools.base import Tool


class FileReaderTool(Tool):
    name = "file_reader"
    description = (
        "Finds and reads invoice files from the company's document store, and extracts "
        "structured fields (company, invoice number, amount, due date) from them. "
        "Actions: 'find' (locate files matching a company name), 'read' (get raw text "
        "of a specific file), 'extract' (parse structured fields from a specific file)."
    )
    input_schema = {
        "action": "one of 'find' | 'read' | 'extract'",
        "company": "company name to search for (required for 'find')",
        "path": "file path (required for 'read' and 'extract')",
    }

    FIELD_PATTERNS = {
        "company": r"Company:\s*(.+)",
        "invoice_number": r"Invoice Number:\s*(.+)",
        "invoice_date": r"Invoice Date:\s*(.+)",
        "amount": r"Amount:\s*₹?\s*([\d,]+(?:\.\d+)?|N/A)",
        "due_date": r"(?:Due Date|Payment Due):\s*(.+)",
    }

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def execute(self, params: dict) -> Observation:
        action = params.get("action")
        if action == "find":
            return self._find(params.get("company", ""))
        elif action == "read":
            return self._read(params.get("path", ""))
        elif action == "extract":
            return self._extract(params.get("path", ""))
        return self._fail(f"Unknown action '{action}'", error_type="invalid_action")

    def _find(self, company: str) -> Observation:
        if not company:
            return self._fail("No company name provided for search.", error_type="invalid_params")

        matches = []
        for file_path in self.base_dir.glob("*.txt"):
            content = file_path.read_text(encoding="utf-8")
            if company.lower() in content.lower():
                matches.append(str(file_path))

        if not matches:
            return self._fail(f"No invoice files found mentioning '{company}'.", error_type="not_found")

        return Observation(
            tool_name=self.name, success=True, raw_output=matches,
            structured_data={"matches": matches}, timestamp=self._now(),
        )

    def _read(self, path: str) -> Observation:
        file_path = Path(path)
        if not file_path.exists():
            return self._fail(f"File not found: {path}", error_type="not_found")

        content = file_path.read_text(encoding="utf-8")
        return Observation(
            tool_name=self.name, success=True, raw_output=content,
            structured_data={"raw_text": content}, timestamp=self._now(),
        )

    def _extract(self, path: str) -> Observation:
        file_path = Path(path)
        if not file_path.exists():
            return self._fail(f"File not found: {path}", error_type="not_found")

        content = file_path.read_text(encoding="utf-8")
        fields, missing = {}, []

        for field_name, pattern in self.FIELD_PATTERNS.items():
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                fields[field_name] = match.group(1).strip()
            else:
                missing.append(field_name)

        invalid_fields = []
        if "amount" in fields:
            cleaned = fields["amount"].replace(",", "")
            if cleaned.upper() == "N/A" or not re.match(r"^\d+(\.\d+)?$", cleaned):
                invalid_fields.append("amount")
            else:
                fields["amount"] = float(cleaned)

        if missing or invalid_fields:
            return Observation(
                tool_name=self.name, success=False, raw_output=content,
                structured_data=fields,  # partial data is still returned — useful downstream
                error_type="missing_field" if missing else "invalid_value",
                error_message=f"Could not extract: {', '.join(missing + invalid_fields)}",
                timestamp=self._now(),
            )

        return Observation(
            tool_name=self.name, success=True, raw_output=content,
            structured_data=fields, timestamp=self._now(),
        )

    def _fail(self, message: str, error_type: str) -> Observation:
        return Observation(
            tool_name=self.name, success=False, raw_output=None, structured_data={},
            error_type=error_type, error_message=message, timestamp=self._now(),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()