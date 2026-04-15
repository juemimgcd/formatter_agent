from typing import Literal

from pydantic import BaseModel, Field


IntentType = Literal["general", "lookup", "collection", "comparison"]


class SearchIntent(BaseModel):
    query: str = Field(..., min_length=1)
    intent_type: IntentType = "general"
    target_schema_name: str = "generic_search_result"
    structured_required: bool = True
    reason: str = ""
