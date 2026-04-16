from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

import httpx
from lxml import html

from conf.settings import settings
from schemas.search_schema import SearchResult
from utils.exceptions import format_exception
from utils.intent_parser import parse_search_intent
from utils.search_support import (
    MAX_SEARCH_RESULTS,
    build_search_http_client,
    canonicalize_search_url,
    extract_source,
    normalize_text,
)

GENERIC_CJK_CHARS = set("作品大全全集列表资料信息相关关于查询搜索内容网页结果")
PROVIDER_BASE_SCORES = {
    "duckduckgo_html": 0.9,
    "bing_html": 0.88,
    "sogou_html": 0.82,
}
TITLE_DUPLICATE_THRESHOLD = 0.92


def extract_significant_cjk_chars(value: str) -> set[str]:
    return {
        char
        for char in normalize_text(value)
        if "\u4e00" <= char <= "\u9fff" and char not in GENERIC_CJK_CHARS
    }


def infer_search_intent_type(query: str) -> str:
    try:
        return parse_search_intent(query).intent_type
    except Exception:
        return "general"


def rewrite_search_queries(query: str, *, max_queries: int = 3) -> list[str]:
    normalized_query = normalize_text(query)
    cleaned = normalized_query
    for noise in ("帮我找", "帮我查", "请帮我", "请找", "一些", "有关", "关于"):
        cleaned = normalize_text(cleaned.replace(noise, " "))

    variants = [normalized_query]
    if cleaned and cleaned != normalized_query:
        variants.append(cleaned)

    intent_type = infer_search_intent_type(cleaned or normalized_query)
    lowered = cleaned.lower()
    if extract_significant_cjk_chars(cleaned):
        if any(term in lowered for term in ("简历", "模板", "样本", "示例")):
            variants.append(f"{cleaned} resume template sample")
        elif intent_type == "comparison":
            variants.append(f"{cleaned} comparison vs best")
        elif intent_type == "collection":
            variants.append(f"{cleaned} list directory ranking")
        elif intent_type == "lookup":
            variants.append(f"{cleaned} guide overview")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in variants:
        value = normalize_text(item)
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            deduped.append(value)
        if len(deduped) >= max_queries:
            break
    return deduped


def calculate_lexical_score(query: str, text: str) -> float:
    normalized_query = normalize_text(query).lower()
    haystack = normalize_text(text).lower()
    if not normalized_query or not haystack:
        return 0.0

    terms = [term for term in normalized_query.split(" ") if term]
    term_score = sum(term in haystack for term in terms) / len(terms) if terms else 0.0
    query_chars = extract_significant_cjk_chars(normalized_query)
    cjk_score = 0.0
    if query_chars:
        cjk_score = len(query_chars & extract_significant_cjk_chars(haystack)) / len(
            query_chars
        )
    return round(max(term_score, cjk_score), 4)


def calculate_intent_pattern_score(query: str, item: SearchResult) -> float:
    text = f"{item.title} {item.snippet} {item.page_excerpt}".lower()
    groups = {
        "template": ("模板", "样本", "示例", "下载", "resume template", "cv sample"),
        "comparison": ("对比", "比较", "区别", "差异", " vs ", "comparison", "compare"),
        "collection": ("列表", "清单", "榜单", "大全", "名单", "list", "directory"),
        "lookup": ("介绍", "指南", "是什么", "overview", "guide", "docs"),
    }
    if any(term in query for term in ("模板", "样本", "示例", "简历")):
        patterns = groups["template"]
    else:
        patterns = groups.get(infer_search_intent_type(query), ())
    return 0.5 if not patterns else round(min(1.0, sum(p in text for p in patterns) / 2), 4)


def score_search_result(query: str, item: SearchResult) -> SearchResult:
    lexical = calculate_lexical_score(query, f"{item.title} {item.snippet} {item.page_excerpt}")
    intent = calculate_intent_pattern_score(query, item)
    domain = (item.source or extract_source(item.url)).lower()
    source = 0.9 if domain.endswith((".edu", ".gov")) else PROVIDER_BASE_SCORES.get(item.provider, 0.75)
    provider_rank = round(1 / max(1, item.provider_rank or item.rank or MAX_SEARCH_RESULTS), 4)
    final = round(0.45 * lexical + 0.20 * intent + 0.20 * source + 0.15 * provider_rank, 4)
    return item.model_copy(
        update={
            "lexical_score": lexical,
            "intent_pattern_score": intent,
            "source_score": round(source, 4),
            "provider_rank_score": provider_rank,
            "final_score": final,
        }
    )


def rank_search_results(query: str, items: list[SearchResult]) -> list[SearchResult]:
    best_by_url: dict[str, SearchResult] = {}
    for item in (score_search_result(query, item) for item in items):
        normalized_url = item.normalized_url or canonicalize_search_url(item.url)
        if not normalized_url:
            continue
        candidate = item.model_copy(update={"normalized_url": normalized_url})
        if normalized_url not in best_by_url or candidate.final_score > best_by_url[normalized_url].final_score:
            best_by_url[normalized_url] = candidate

    ranked = sorted(best_by_url.values(), key=lambda item: item.final_score, reverse=True)
    deduped: list[SearchResult] = []
    for item in ranked:
        title = re.sub(r"[^\w\u4e00-\u9fff]+", "", item.title.lower())
        if any(
            SequenceMatcher(
                None,
                title,
                re.sub(r"[^\w\u4e00-\u9fff]+", "", existing.title.lower()),
            ).ratio()
            >= TITLE_DUPLICATE_THRESHOLD
            for existing in deduped
        ):
            continue
        deduped.append(item)
    return [
        item.model_copy(update={"rank": index, "notes": [*item.notes, "ranked"]})
        for index, item in enumerate(deduped, start=1)
    ]


def extract_page_excerpt(page_text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    try:
        tree = html.fromstring(page_text)
    except Exception:
        return normalize_text(page_text)[:max_chars]

    for node in tree.xpath("//script|//style|//noscript|//svg"):
        if node.getparent() is not None:
            node.getparent().remove(node)

    description_xpath = (
        "//meta[translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='description']/@content"
        " | //meta[translate(@property, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='og:description']/@content"
    )
    parts = [
        " ".join(tree.xpath("//title//text()")),
        " ".join(tree.xpath(description_xpath)),
        " ".join(tree.xpath("//body//text()")),
    ]
    return normalize_text(" ".join(part for part in parts if part))[:max_chars]


async def fetch_page_excerpt(client: httpx.AsyncClient, item: SearchResult) -> SearchResult:
    if urlparse(item.url).scheme not in {"http", "https"}:
        return item.model_copy(update={"notes": [*item.notes, "enrich_skipped_non_http"]})
    try:
        response = await client.get(item.url)
        response.raise_for_status()
        excerpt = extract_page_excerpt(
            response.text,
            max_chars=settings.search_enrich_excerpt_chars,
        )
    except Exception as exc:
        return item.model_copy(update={"notes": [*item.notes, f"enrich_failed={format_exception(exc)}"]})
    return item.model_copy(
        update={
            "page_excerpt": excerpt,
            "notes": [*item.notes, "enriched" if excerpt else "enrich_empty"],
        }
    )


async def enrich_search_results(items: list[SearchResult]) -> list[SearchResult]:
    top_k = max(0, int(settings.search_enrich_top_k))
    if not items or top_k <= 0:
        return items
    async with build_search_http_client() as client:
        enriched = await asyncio.gather(
            *[fetch_page_excerpt(client, item) for item in items[:top_k]]
        )
    return [*enriched, *items[top_k:]]
