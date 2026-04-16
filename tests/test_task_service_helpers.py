from schemas import SearchResult
from schemas.search_schema import CandidateResultItem, StructuredResultItem
from utils.task_service_helpers import (
    build_candidates,
    filter_structured_items_by_candidates,
    score_candidate,
    select_top_candidates,
)


def search_result_item(
    *,
    title: str,
    url: str,
    snippet: str = "",
    source: str = "example.com",
    rank: int = 1,
) -> SearchResult:
    # 构造任务 helper 测试使用的搜索结果对象。
    return SearchResult(
        title=title,
        url=url,
        snippet=snippet,
        source=source,
        rank=rank,
    )


def test_select_top_candidates_deduplicates_and_reranks_by_query():
    candidates = build_candidates(
        "task-001",
        [
            search_result_item(
                title="通用资料汇总",
                url="https://example.com/a",
                snippet="只有一些背景说明",
                rank=1,
            ),
            search_result_item(
                title="AI 产品经理岗位解析",
                url="https://example.com/pm",
                snippet="AI 产品经理 能力要求与职责",
                rank=2,
            ),
            search_result_item(
                title="AI 产品经理岗位解析（重复链接）",
                url="https://example.com/pm/",
                snippet="重复结果，不应该保留两次",
                rank=3,
            ),
        ],
        search_provider="sogou_html",
    )

    selected = select_top_candidates("AI 产品经理", candidates, top_k=5)

    assert len(selected) == 1
    assert selected[0].url == "https://example.com/pm"
    assert selected[0].title == "AI 产品经理岗位解析"


def test_select_top_candidates_filters_unrelated_chinese_results():
    candidates = build_candidates(
        "task-zhang",
        [
            search_result_item(
                title="张雪峰去世是假消息",
                url="https://example.com/zhang-xuefeng",
                snippet="这条内容和导演作品无关",
                rank=1,
            ),
            search_result_item(
                title="张艺谋作品大全",
                url="https://example.com/zhang-yimou",
                snippet="整理张艺谋导演电影作品、代表作和获奖信息",
                rank=2,
            ),
        ],
        search_provider="bing_html",
    )

    selected = select_top_candidates("张艺谋作品大全", candidates, top_k=5)

    assert len(selected) == 1
    assert selected[0].title == "张艺谋作品大全"
    assert score_candidate("张艺谋作品大全", candidates[0]) < 0.5


def test_filter_structured_items_by_candidates_drops_unknown_llm_url():
    candidates = [
        CandidateResultItem(
            candidate_id="task-01",
            title="张艺谋作品大全",
            url="https://example.com/zhang-yimou",
            source="example.com",
            summary="整理张艺谋导演电影作品",
            rerank_score=1,
        )
    ]
    items = [
        StructuredResultItem(
            query="张艺谋作品大全",
            title="张雪峰去世",
            source="example.com",
            url="https://example.com/zhang-xuefeng",
            summary="错误跑偏结果",
            quality_score=80,
        ),
        StructuredResultItem(
            query="张艺谋作品大全",
            title="张艺谋作品大全",
            source="example.com",
            url="https://example.com/zhang-yimou",
            summary="整理张艺谋导演电影作品",
            quality_score=85,
        ),
    ]

    result = filter_structured_items_by_candidates(
        "张艺谋作品大全",
        items,
        candidates,
    )

    assert [item.title for item in result.items] == ["张艺谋作品大全"]
    assert result.warnings == ["drop structured item with unknown url: 张雪峰去世"]
