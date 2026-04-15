from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    name: str
    tool_name: str
    description: str = ""
    required: bool = True


class ExecutionPlan(BaseModel):
    plan_id: str
    intent_type: str
    schema_name: str
    steps: list[PlanStep] = Field(default_factory=list)
    summary: str = ""


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


class TaskMemory(BaseModel):
    task_id: str
    intent_type: str = "general"
    schema_name: str = "generic_search_result"
    plan_id: str = ""
    raw_result_count: int = 0
    selected_candidate_count: int = 0
    structured_result_count: int = 0
    used_fallback: bool = False
    result_quality: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
