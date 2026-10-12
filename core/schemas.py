"""
Pydantic schemas — the data contracts every component in the system agrees on.
Designing these carefully upfront is what makes structured LLM output,
independent verification, and clean logging possible later.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DecisionType(str, Enum):
    ACT = "act"
    REPLAN = "replan"
    ASK_HUMAN = "ask_human"
    DECLARE_DONE = "declare_done"


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"       # worth retrying (timeout, rate limit)
    PERMANENT = "permanent"       # retrying won't help (resource genuinely missing)
    AMBIGUOUS = "ambiguous"       # unsafe to guess — must ask human
    NONE = "none"                 # no error, action succeeded


class VerdictStatus(str, Enum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    FAILED = "failed"
    CANNOT_VERIFY = "cannot_verify"


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

class SuccessCriterion(BaseModel):
    id: str
    description: str = Field(..., description="Human-readable statement of what must be true for this criterion to pass.")
    check_type: str = Field(..., description="How to verify this, e.g. 'api_query', 'db_query', 'file_check'.")
    check_target: str = Field(..., description="Endpoint, table, or file path to check against.")
    expected_field: str = Field(..., description="Field name expected to hold the result.")
    expected_source: str = Field(..., description="Key in working memory holding the expected value to compare against.")


class Plan(BaseModel):
    steps: list[str] = Field(..., description="Draft sequence of actions. Treated as a hypothesis, not a rigid script.")
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)   # <-- changed: LLM may leave empty; task config is authoritative
    reasoning: str = Field(..., description="Why this plan was chosen, for auditability.")


# ---------------------------------------------------------------------------
# Execution / Observation
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    tool_name: str
    params_json: str = Field(
        default="{}",
        description=(
            "Parameters for the tool call, encoded as a JSON string, e.g. "
            '\'{"action": "find", "company": "Company X"}\'. '
            "Must be valid JSON. Use {} if the tool needs no parameters."
        ),
    )


class Observation(BaseModel):
    tool_name: str
    success: bool
    raw_output: Any = None
    structured_data: dict[str, Any] = Field(default_factory=dict)
    error_type: Optional[str] = None     # e.g. "timeout", "not_found", "validation_error"
    error_message: Optional[str] = None
    timestamp: str


# ---------------------------------------------------------------------------
# Decision Engine
# ---------------------------------------------------------------------------

class Decision(BaseModel):
    type: DecisionType
    reasoning: str = Field(..., description="Why the agent is choosing this action right now.")
    tool_call: Optional[ToolCall] = None          # populated when type == ACT
    question_for_human: Optional[str] = None      # populated when type == ASK_HUMAN
    replan_context: Optional[str] = None          # populated when type == REPLAN


# ---------------------------------------------------------------------------
# Error Classification
# ---------------------------------------------------------------------------

class ErrorClassification(BaseModel):
    category: ErrorCategory
    should_retry: bool
    suggested_alternative: Optional[str] = None
    reasoning: str


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

class CriterionResult(BaseModel):
    criterion_id: str
    passed: bool
    actual_value: Any = None
    expected_value: Any = None
    notes: str = ""


class Verdict(BaseModel):
    status: VerdictStatus
    criterion_results: list[CriterionResult]
    summary: str


# ---------------------------------------------------------------------------
# Human-in-the-loop
# ---------------------------------------------------------------------------

class HumanRequest(BaseModel):
    question: str
    context: dict[str, Any] = Field(default_factory=dict)


class HumanResponse(BaseModel):
    answer: str
    approved: Optional[bool] = None


# ---------------------------------------------------------------------------
# Final Output
# ---------------------------------------------------------------------------

class TaskSummary(BaseModel):
    task_id: str
    goal: str
    final_status: VerdictStatus
    summary_text: str
    evidence: list[str] = Field(default_factory=list, description="Pointers to logs, screenshots, DB records, etc.")