import json

from schemas import CandidateResultItem
from utils.retriever import (
    build_rebuild_prompt_input,
    build_rebuild_prompt_payload,
    trim_text,
)


def candidate_item(
    *, candidate_id: str, title: str, url: str, score: float, summary: str, notes: str
):
    # 构造 retriever 测试需要的候选结果对象。
    return CandidateResultItem(
        candidate_id=candidate_id,
        title=title,
        url=url,
        source="web",
        chunk_id="chunk-1",
        summary=summary,
        extraction_notes=notes,
        rerank_score=score,
    )


def test_trim_text_preserves_short_text_and_truncates_long_text():
    assert trim_text("  short text  ", 20) == "short text"
    assert trim_text("abcdef", 3) == "abc..."
    assert trim_text("abcdef", 0) == "abcdef"


def test_build_rebuild_prompt_payload_filters_empty_urls_and_applies_defaults():
    items = [
        candidate_item(
            candidate_id="c1",
            title="  ",
            url="https://example.com",
            score=0.8,
            summary="a" * 30,
            notes="n" * 300,
        ),
        candidate_item(
            candidate_id="c2",
            title="skip",
            url=" ",
            score=0.1,
            summary="summary",
            notes="notes",
        ),
    ]

    payload = build_rebuild_prompt_payload(
        "AI 产品经理",
        items,
        max_items=5,
        max_summary_len=12,
    )

    assert payload["query"] == "AI 产品经理"
    assert len(payload["top_candidates"]) == 1
    first = payload["top_candidates"][0]
    assert first["title"] == "未命名结果"
    assert first["summary"] == "aaaaaaaaaaaa..."
    assert first["extraction_notes"].endswith("...")


def test_build_rebuild_prompt_input_returns_json_text():
    payload_text = build_rebuild_prompt_input(
        "AI 产品经理",
        [
            candidate_item(
                candidate_id="c1",
                title="title",
                url="https://example.com",
                score=0.8,
                summary="summary",
                notes="notes",
            )
        ],
    )

    payload = json.loads(payload_text)

    assert payload["query"] == "AI 产品经理"
    assert payload["top_candidates"][0]["url"] == "https://example.com"
