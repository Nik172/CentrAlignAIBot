"""
Rule-based (not LLM-based) error classification. Deterministic on purpose:
retry/escalation policy should be predictable and auditable, not subject
to LLM mood swings.
"""
from core.schemas import Observation, ErrorClassification, ErrorCategory


class ErrorClassifier:
    TRANSIENT = {"timeout", "server_error", "connection_error"}
    AMBIGUOUS = {"missing_field", "invalid_value"}
    PERMANENT = {"not_found", "http_error", "invalid_action", "invalid_params", "unknown_tool"}

    def classify(self, observation: Observation) -> ErrorClassification:
        et = observation.error_type or "none"
        if et in self.TRANSIENT:
            return ErrorClassification(
                category=ErrorCategory.TRANSIENT, should_retry=True,
                reasoning=f"'{et}' is typically transient; retrying with backoff is safe.")
        if et in self.AMBIGUOUS:
            return ErrorClassification(
                category=ErrorCategory.AMBIGUOUS, should_retry=False,
                suggested_alternative="ask_human",
                reasoning=f"'{et}' requires human judgment; the agent must not guess.")
        if et in self.PERMANENT:
            return ErrorClassification(
                category=ErrorCategory.PERMANENT, should_retry=False,
                suggested_alternative="ask_human",
                reasoning=f"'{et}' will not resolve via retry.")
        return ErrorClassification(category=ErrorCategory.NONE, should_retry=False, reasoning="No error.")