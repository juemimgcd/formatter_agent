from datetime import datetime

from pydantic import BaseModel


class StageTimestampPatch(BaseModel):
    search_finished_at: datetime | None = None
    llm_finished_at: datetime | None = None
    export_finished_at: datetime | None = None