from __future__ import annotations

from lxml import html

from conf.settings import settings
from schemas.search_schema import SearchResult
from utils.exceptions import WorkflowError
from utils.search_support import (
    build_search_http_client,
    canonicalize_search_url,
    extract_source,
    normalize_result_url,
    normalize_text,
)

DEFAULT_SEARCH_PROVIDER_ORDER = ["duckduckgo_html", "bing_html", "sogou_html"]
SEARCH_PROVIDER_NAMES = set(DEFAULT_SEARCH_PROVIDER_ORDER)


def build_search_result(
    *,
    title: str,
    url: str,
    snippet: str,
    rank: int,
) -> SearchResult | None:
    title = normalize_text(title)
    url = normalize_text(url)
    if not title or not url:
        return None
    return SearchResult(
        title=title,
        url=url,
        snippet=normalize_text(snippet),
        source=extract_source(url),
        rank=rank,
    )


def deduplicate_search_results(items: list[SearchResult]) -> list[SearchResult]:
    deduped: list[SearchResult] = []
    seen: set[str] = set()
    for item in items:
        normalized_url = canonicalize_search_url(item.url)
        if not normalized_url or normalized_url in seen:
            continue
        seen.add(normalized_url)
        deduped.append(
            item.model_copy(
                update={
                    "rank": len(deduped) + 1,
                    "normalized_url": normalized_url,
                }
            )
        )
    return deduped


def parse_duckduckgo_html_results(page_text: str, *, max_results: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for node in html.fromstring(page_text).xpath("//div[contains(@class, 'web-result')]"):
        result = build_search_result(
            title="".join(node.xpath(".//a[contains(@class, 'result__a')]//text()")),
            url=node.xpath("string(.//a[contains(@class, 'result__a')]/@href)"),
            snippet=" ".join(node.xpath(".//*[contains(@class, 'result__snippet')]//text()")),
            rank=len(results) + 1,
        )
        if result is not None:
            results.append(result)
        if len(results) >= max_results:
            break
    return deduplicate_search_results(results)


def is_duckduckgo_anomaly_page(page_text: str) -> bool:
    lowered = page_text.lower()
    return "anomaly.js" in lowered or 'id="challenge-form"' in lowered


def parse_bing_html_results(page_text: str, *, max_results: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for node in html.fromstring(page_text).xpath("//li[contains(@class,'b_algo')][.//h2//a[@href]]"):
        result = build_search_result(
            title="".join(node.xpath(".//h2//a//text()")),
            url=normalize_result_url(
                node.xpath("string(.//h2//a/@href)"),
                base_url="https://www.bing.com",
            ),
            snippet=" ".join(node.xpath(".//p//text()")),
            rank=len(results) + 1,
        )
        if result is not None:
            results.append(result)
        if len(results) >= max_results:
            break
    return deduplicate_search_results(results)


def is_bing_captcha_page(page_text: str) -> bool:
    lowered = page_text.lower()
    return "captcha" in lowered and "b_algo" not in lowered


def pick_sogou_snippet(node: html.HtmlElement, title: str) -> str:
    candidates: list[str] = []
    xpath = (
        ".//p//text() | .//div[contains(@class,'space-txt')]//text()"
        " | .//div[contains(@class,'fz-mid')]//text()"
    )
    for text in node.xpath(xpath):
        normalized = normalize_text(text)
        if normalized and normalized != title and len(normalized) >= 12:
            candidates.append(normalized)
    return max(candidates, key=len, default="")


def parse_sogou_html_results(page_text: str, *, max_results: int) -> list[SearchResult]:
    tree = html.fromstring(page_text)
    results: list[SearchResult] = []
    for title_node in tree.xpath("//h3[.//a[@href]]"):
        parent = title_node.getparent()
        container = parent if parent is not None else title_node
        title = normalize_text("".join(title_node.xpath(".//text()")))
        result = build_search_result(
            title=title,
            url=normalize_result_url(
                title_node.xpath("string(.//a/@href)"),
                base_url="https://www.sogou.com",
            ),
            snippet=pick_sogou_snippet(container, title),
            rank=len(results) + 1,
        )
        if result is not None:
            results.append(result)
        if len(results) >= max_results:
            break
    return deduplicate_search_results(results)


async def search_duckduckgo_html(query: str, *, max_results: int) -> list[SearchResult]:
    async with build_search_http_client() as client:
        response = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": settings.search_region},
        )
        response.raise_for_status()
    if is_duckduckgo_anomaly_page(response.text):
        raise WorkflowError("DuckDuckGo 返回反爬挑战页")
    return parse_duckduckgo_html_results(response.text, max_results=max_results)


async def search_bing_html(query: str, *, max_results: int) -> list[SearchResult]:
    async with build_search_http_client() as client:
        response = await client.get("https://www.bing.com/search", params={"q": query})
        response.raise_for_status()
    if is_bing_captcha_page(response.text):
        raise WorkflowError("Bing 返回验证码页")
    return parse_bing_html_results(response.text, max_results=max_results)


async def search_sogou_html(query: str, *, max_results: int) -> list[SearchResult]:
    async with build_search_http_client() as client:
        response = await client.get("https://www.sogou.com/web", params={"query": query})
        response.raise_for_status()
    return parse_sogou_html_results(response.text, max_results=max_results)
