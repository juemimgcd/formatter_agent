
from schemas.intent_schema import SearchIntent
from utils.task_service_helpers import clean_text


COLLECTION_SIGNALS = ("有哪些", "列表", "清单", "大全", "推荐", "top", "best", "list")
COMPARISON_SIGNALS = ("对比", "比较", "区别", "差异", "vs", "versus", "compare")
LOOKUP_SIGNALS = ("是什么", "介绍", "资料", "信息", "指南", "如何", "怎么", "overview", "guide")


def parse_search_intent(query: str) -> SearchIntent:
    # 根据查询文本中的关键词信号判断本次搜索的意图类型。
    normalized_query = clean_text(query)
    lowered = normalized_query.lower()

    if any(signal in lowered for signal in COMPARISON_SIGNALS):
        return SearchIntent(
            query=normalized_query,
            intent_type="comparison",
            target_schema_name="generic_search_result",
            reason="query 命中对比 / 差异类表达，按 comparison 查询形态处理",
        )

    if any(signal in lowered for signal in COLLECTION_SIGNALS):
        return SearchIntent(
            query=normalized_query,
            intent_type="collection",
            target_schema_name="generic_search_result",
            reason="query 命中列表 / 集合类表达，按 collection 查询形态处理",
        )

    if any(signal in lowered for signal in LOOKUP_SIGNALS):
        return SearchIntent(
            query=normalized_query,
            intent_type="lookup",
            target_schema_name="generic_search_result",
            reason="query 命中资料 / 介绍类表达，按 lookup 查询形态处理",
        )

    return SearchIntent(
        query=normalized_query,
        intent_type="general",
        target_schema_name="generic_search_result",
        reason="未命中特定查询形态信号，按开放领域通用查询处理",
    )
