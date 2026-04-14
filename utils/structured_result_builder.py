from __future__ import annotations

from langchain_core.output_parsers import PydanticOutputParser

from schemas import StructuredResultItem, StructuredResultSet
from utils.exceptions import ExtractionError
from utils.llm import get_llm
from utils.result_prompt import get_structured_result_prompt


async def build_structured_results(
    *,
    query: str,
    rebuilt_prompt_input_text: str,
    max_output_items: int = 5,
) -> list[StructuredResultItem]:
    """第二段 LLM：基于 rebuild_prompt 输入一次性产出结构化结果列表。"""

    parser = PydanticOutputParser(pydantic_object=StructuredResultSet)
    prompt = get_structured_result_prompt(
        format_instructions=parser.get_format_instructions(),
        max_items=max_output_items,
    )
    llm = get_llm()
    chain = prompt | llm | parser

    try:
        result = await chain.ainvoke(
            {
                "query": query,
                "rebuilt_prompt_input_text": rebuilt_prompt_input_text,
            }
        )
    except Exception as exc:
        raise ExtractionError(f"第二段结构化抽取失败: {exc}") from exc

    items = list(getattr(result, "items", []))[:max_output_items]
    fixed: list[StructuredResultItem] = []
    for item in items:
        fixed.append(item.model_copy(update={"query": item.query or query}))
    return fixed
