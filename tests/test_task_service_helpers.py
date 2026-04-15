from schemas import SearchResult
from utils.task_service_helpers import build_candidates, select_top_candidates


def _search_result(
    *,
    title: str,
    url: str,
    snippet: str = "",
    source: str = "example.com",
    rank: int = 1,
) -> SearchResult:
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
            _search_result(
                title="通用资料汇总",
                url="https://example.com/a",
                snippet="只有一些背景说明",
                rank=1,
            ),
            _search_result(
                title="AI 产品经理岗位解析",
                url="https://example.com/pm",
                snippet="AI 产品经理 能力要求与职责",
                rank=2,
            ),
            _search_result(
                title="AI 产品经理岗位解析（重复链接）",
                url="https://example.com/pm/",
                snippet="重复结果，不应该保留两次",
                rank=3,
            ),
        ],
        search_provider="sogou_html",
    )

    selected = select_top_candidates("AI 产品经理", candidates, top_k=5)

    assert len(selected) == 2
    assert selected[0].url == "https://example.com/pm"
    assert selected[0].title == "AI 产品经理岗位解析"
    assert selected[1].url == "https://example.com/a"
