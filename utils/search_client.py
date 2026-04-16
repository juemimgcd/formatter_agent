from __future__ import annotations

import asyncio

from conf.logging_conf import app_logger
from conf.settings import settings
from schemas.search_schema import SearchResult
from utils.exceptions import WorkflowError, format_exception
from utils.search_pipeline import (
    enrich_search_results,
    extract_page_excerpt,
    rank_search_results,
    rewrite_search_queries,
)
from utils.search_providers import (
    DEFAULT_SEARCH_PROVIDER_ORDER,
    SEARCH_PROVIDER_NAMES,
    is_bing_captcha_page,
    parse_bing_html_results,
    parse_duckduckgo_html_results,
    parse_sogou_html_results,
    search_bing_html,
    search_duckduckgo_html,
    search_sogou_html,
)
from utils.search_support import (
    MAX_SEARCH_RESULTS,
    canonicalize_search_url,
    normalize_search_limit,
    normalize_text,
)

SEARCH_LOGGER = app_logger.bind(module="search_client")


def get_search_provider_names(provider: str) -> list[str]:
    provider = normalize_text(provider).lower()
    if provider == "auto":
        return list(DEFAULT_SEARCH_PROVIDER_ORDER)
    return [provider] if provider in SEARCH_PROVIDER_NAMES else []


async def run_search_provider(
    provider_name: str,
    query: str,
    *,
    max_results: int,
) -> list[SearchResult]:
    provider_map = {
        "duckduckgo_html": search_duckduckgo_html,
        "bing_html": search_bing_html,
        "sogou_html": search_sogou_html,
    }
    if provider_name not in provider_map:
        raise WorkflowError(f"不支持的搜索提供方: {provider_name}")
    return await provider_map[provider_name](query, max_results=max_results)


async def run_provider_query(
    provider_name: str,
    query: str,
    *,
    max_results: int,
) -> tuple[list[SearchResult], str | None]:
    try:
        results = await run_search_provider(provider_name, query, max_results=max_results)
    except Exception as exc:
        return [], f"{provider_name} failed: {format_exception(exc)}"
    if not results:
        return [], f"{provider_name} returned empty result"

    return [
        item.model_copy(
            update={
                "provider": provider_name,
                "provider_rank": item.rank,
                "normalized_url": canonicalize_search_url(item.url),
                "notes": [*item.notes, f"query={query}"],
            }
        )
        for item in results
    ], None


async def collect_provider_results(
    provider_names: list[str],
    queries: list[str],
    *,
    max_results: int,
) -> tuple[list[SearchResult], list[str]]:
    tasks = [
        run_provider_query(provider_name, query, max_results=max_results)
        for provider_name in provider_names
        for query in queries
    ]
    outputs = await asyncio.gather(*tasks) if tasks else []
    results = [item for provider_results, _ in outputs for item in provider_results]
    warnings = [warning for _, warning in outputs if warning]
    return results, warnings


def attach_search_warnings(
    results: list[SearchResult],
    warnings: list[str],
) -> list[SearchResult]:
    if not results or not warnings:
        return results
    return [
        results[0].model_copy(
            update={
                "notes": [
                    *results[0].notes,
                    *[f"search_warning={warning}" for warning in warnings],
                ]
            }
        ),
        *results[1:],
    ]


async def search_web(
    query: str,
    *,
    max_results: int | None = None,
) -> list[SearchResult]:
    query = normalize_text(query)
    if not query:
        return []

    limit = normalize_search_limit(max_results)
    provider_names = get_search_provider_names(settings.search_provider)
    if not provider_names:
        raise WorkflowError(f"不支持的搜索提供方: {settings.search_provider}")

    rewrites = rewrite_search_queries(query)
    raw_results, warnings = await collect_provider_results(
        provider_names,
        rewrites,
        max_results=min(MAX_SEARCH_RESULTS, max(5, limit)),
    )
    ranked_results = rank_search_results(query, raw_results)
    final_results = attach_search_warnings(
        await enrich_search_results(ranked_results[:limit]),
        warnings,
    )

    SEARCH_LOGGER.info(
        "query={!r} providers={} rewrites={} raw_count={} ranked_count={} enriched_count={} warnings={}",
        query,
        provider_names,
        rewrites,
        len(raw_results),
        len(ranked_results),
        sum(1 for item in final_results if item.page_excerpt),
        warnings,
    )
    if final_results:
        return final_results
    raise WorkflowError("; ".join(warnings) or "all search providers failed")
