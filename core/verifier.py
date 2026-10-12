"""
Independent verification: re-queries the actual system state directly,
rather than trusting the executor's self-reported success. This is the
single most important reliability mechanism in the system — it's what
catches "the agent thinks it worked but the DB disagrees" scenarios.
Deterministic, rule-based — no LLM call, so verification can't be fooled
by model hallucination either.
"""
from core.schemas import SuccessCriterion, CriterionResult, Verdict, VerdictStatus
from core.tools.api_tool import ApiTool


class Verifier:
    def __init__(self, api_tool: ApiTool):
        self.api_tool = api_tool

    def verify(self, criteria: list[SuccessCriterion], working_memory: dict) -> Verdict:
        results = []
        for c in criteria:
            if c.check_type != "api_query":
                results.append(CriterionResult(criterion_id=c.id, passed=False,
                                                notes=f"Unsupported check_type: {c.check_type}"))
                continue

            obs = self.api_tool.execute({
                "method": "GET", "path": c.check_target,
                "query": {"company": working_memory.get("company", "")},
            })
            if not obs.success:
                results.append(CriterionResult(criterion_id=c.id, passed=False,
                                                notes=f"Could not query system: {obs.error_message}"))
                continue

            records = obs.structured_data.get("result", [])
            if not records:
                results.append(CriterionResult(criterion_id=c.id, passed=False,
                                                notes="No matching record found in system."))
                continue

            record = records[0]  # most recent (API returns DESC order)
            actual = record.get(c.expected_field, "<MISSING>")
            expected = working_memory.get(c.expected_source, "<UNKNOWN>")
            passed = self._values_match(actual, expected)
            results.append(CriterionResult(
                criterion_id=c.id, passed=passed, actual_value=actual, expected_value=expected,
                notes="" if passed else "Mismatch or field missing in system response.",
            ))

        statuses = [r.passed for r in results]
        if all(statuses):
            status = VerdictStatus.VERIFIED
        elif any(statuses):
            status = VerdictStatus.PARTIAL
        else:
            status = VerdictStatus.FAILED

        summary = "; ".join(f"{r.criterion_id}: {'OK' if r.passed else 'FAILED - ' + r.notes}" for r in results)
        return Verdict(status=status, criterion_results=results, summary=summary)

    @staticmethod
    def _values_match(actual, expected) -> bool:
        if actual == "<MISSING>":
            return False
        try:
            return abs(float(actual) - float(expected)) < 0.01
        except (TypeError, ValueError):
            return str(actual).strip().lower() == str(expected).strip().lower()