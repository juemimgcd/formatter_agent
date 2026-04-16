from typing import Any, Literal

from pydantic import BaseModel, Field

from schemas.search_schema import CandidateResultItem, StructuredResultItem


class OutputSchemaField(BaseModel):
    name: str
    description: str = ""
    required: bool = True


class OutputSchema(BaseModel):
    name: str
    version: str = "v1"
    description: str = ""
    fields: list[OutputSchemaField] = Field(default_factory=list)

    @property
    def required_fields(self) -> list[str]:
        return [field.name for field in self.fields if field.required]


ActionType = Literal["search", "targeted_search", "verify", "finalize"]
ObservationType = Literal[
    "search_result",
    "search_failed",
    "structured_result",
    "verify_result",
    "final_output",
    "unsupported_action",
]


class StateSchemaPayload(BaseModel):
    name: str
    version: str = "v1"
    description: str = ""
    fields: list[OutputSchemaField] = Field(default_factory=list)
    output_required_fields: list[str] = Field(default_factory=list)
    required_slots: list[str] = Field(default_factory=list)


class AgentAction(BaseModel):
    type: ActionType
    query: str = ""
    field: str | None = None
    value: Any = None
    reason: str = ""


class ToolObservation(BaseModel):
    type: ObservationType
    summary: str = ""
    raw_count: int = 0
    selected_count: int = 0
    candidates: list[CandidateResultItem] = Field(default_factory=list)
    items: list[StructuredResultItem] = Field(default_factory=list)
    used_fallback: bool = False
    result_quality: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
    prompt_chars: int = 0
    excel_path: str | None = None
    field: str | None = None
    verified: bool = False
    error: str | None = None
    warning: str | None = None


class AgentRuntimeResult(BaseModel):
    raw_result_count: int = 0
    selected_candidate_count: int = 0
    structured_result_count: int = 0
    candidates: list[CandidateResultItem] = Field(default_factory=list)
    items: list[StructuredResultItem] = Field(default_factory=list)
    used_fallback: bool = False
    result_quality: str = "unknown"
    excel_path: str | None = None
    error: str | None = None


class AgentTraceItem(BaseModel):
    round_idx: int
    action_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    summary: str = ""


class AgentOutput(BaseModel):
    result: AgentRuntimeResult
    warnings: list[str] = Field(default_factory=list)
    stop_reason: str | None = None
    trace: list[AgentTraceItem] = Field(default_factory=list)
    evidence_count: int = 0
    slots: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
