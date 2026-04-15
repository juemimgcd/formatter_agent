from __future__ import annotations

from langchain_core.output_parsers import PydanticOutputParser

from schemas.search_schema import StructuredResultItem, StructuredResultSet
from utils.llm import get_llm
from utils.result_prompt import get_structured_result_prompt


def normalize_structured_item(
    query: str, item: StructuredResultItem
) -> StructuredResultItem:
    return item.model_copy(
        update={
            "query": (item.query or "").strip() or query,
            "title": (item.title or "").strip() or "未命名结果",
            "source": (item.source or "").strip() or "unknown",
            "url": (item.url or "").strip(),
            "content_type": (item.content_type or "").strip() or "unknown",
            "region": (item.region or "").strip() or "不限",
            "role_direction": (item.role_direction or "").strip() or "通用",
            "summary": (item.summary or "").strip(),
            "quality_score": max(0, min(100, int(item.quality_score or 0))),
            "extraction_notes": (item.extraction_notes or "").strip(),
        }
    )


async def build_structured_results(
    *,
    query: str,
    rebuilt_prompt_input_text: str,
    max_output_items: int,
) -> list[StructuredResultItem]:
    parser = PydanticOutputParser(pydantic_object=StructuredResultSet)
    prompt = get_structured_result_prompt(
        parser.get_format_instructions(),
        max_items=max_output_items,
    )
    chain = prompt | get_llm() | parser
    result = await chain.ainvoke(
        {
            "query": query,
            "rebuilt_prompt_input_text": rebuilt_prompt_input_text,
        }
    )

    items = StructuredResultSet.model_validate(result).items
    normalized_items: list[StructuredResultItem] = []
    for item in items[:max_output_items]:
        normalized = normalize_structured_item(query, item)
        if not normalized.url:
            continue
        normalized_items.append(normalized)

    return normalized_items
