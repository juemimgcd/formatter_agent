from langchain_core.prompts import ChatPromptTemplate


def get_structured_result_prompt(
    format_instructions: str, max_items: int = 10
) -> ChatPromptTemplate:
    """构造结构化整理阶段使用的 ChatPromptTemplate。

    Args:
        format_instructions: 由输出解析器提供的格式约束说明（通常是 JSON schema / 字段规则）。
        max_items: 允许输出的最大条数。

    Returns:
        可直接与 LLM/Parser 组成链路的 LangChain prompt。
    """
    # 生成结构化结果整理阶段使用的提示词模板。
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是一个结构化搜索结果整理助手。"
                "你会基于用户 query 和 top_k 高分结果（rebuild_prompt 输入），整理成最终结构化结果。"
                f"输出条数不超过 {max_items} 条，按相关性和可靠性从高到低排序。"
                "你只能依据输入内容做判断，不能编造页面中不存在的信息。"
                "如果信息不足，请使用保守默认值。"
                "必须输出完整字段：query, title, source, url, content_type, region, role_direction, summary, quality_score, extraction_notes。"
                "quality_score 必须是 0 到 100 的整数。"
                "输出必须严格遵守格式要求。",
            ),
            (
                "human",
                "query={query}\n\n"
                "rebuilt_prompt_input=\n{rebuilt_prompt_input_text}\n\n"
                "{format_instructions}",
            ),
        ]
    ).partial(format_instructions=format_instructions)
