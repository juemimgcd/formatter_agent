from __future__ import annotations

import re
from urllib.parse import urljoin
from urllib.parse import urlparse

import httpx
from lxml import html

from conf.settings import settings
from schemas.search_schema import SearchResult
from utils.exceptions import WorkflowError

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
}
MAX_SEARCH_RESULTS = 10





def normalize_text(value: str) -> str:
    """归一化文本：去除首尾空白并压缩多余空格。"""
    # 统一清洗文本中的空白字符，便于后续比较和展示。
    return re.sub(r"\s+", " ", (value or "").strip())


def extract_source(url: str) -> str:
    """从 URL 中提取来源域名（用于结果展示与统计）。"""
    # 从链接中提取标准化后的来源域名。
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "web"


def normalize_search_limit(max_results: int | None) -> int:
    """将请求的 max_results 规范到允许范围内（并应用默认配置）。"""
    # 把请求的结果条数约束到系统允许的范围内。
    limit = max_results or settings.search_result_limit
    limit = int(limit)

    if limit < 1:
        return 1
    if limit > MAX_SEARCH_RESULTS:
        return MAX_SEARCH_RESULTS
    return limit


def normalize_result_url(url: str, *, base_url: str) -> str:
    """把相对链接补全成完整 URL。"""
    # 将原始结果链接规范成可直接访问的绝对地址。
    return normalize_text(urljoin(base_url, url))


def parse_duckduckgo_html_results(
    page_text: str, *, max_results: int
) -> list[SearchResult]:
    """解析 DuckDuckGo HTML 搜索页，提取结果列表。
    该解析器仅抽取 title/url/snippet，并基于 URL 做简单去重。
    """
    # 从 DuckDuckGo 的 HTML 页面中解析出结构化搜索结果。
    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for node in html.fromstring(page_text).xpath(
        "//div[contains(@class, 'web-result')]"
    ):
        title = normalize_text(
            "".join(node.xpath(".//a[contains(@class, 'result__a')]//text()"))
        )
        url = normalize_text(
            node.xpath("string(.//a[contains(@class, 'result__a')]/@href)")
        )
        snippet = normalize_text(
            " ".join(node.xpath(".//*[contains(@class, 'result__snippet')]//text()"))
        )

        if not title or not url:
            continue

        dedup_key = url.rstrip("/").lower()
        if dedup_key in seen_urls:
            continue
        seen_urls.add(dedup_key)

        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                source=extract_source(url),
                rank=len(results) + 1,
            )
        )
        if len(results) >= max_results:
            break

    return results


def is_duckduckgo_anomaly_page(page_text: str) -> bool:
    """判断 DuckDuckGo 是否返回了反爬挑战页。"""
    # 检测返回页面是否属于 DuckDuckGo 的异常或反爬响应。
    lowered = page_text.lower()
    return "anomaly.js" in lowered or 'id="challenge-form"' in lowered


def _pick_sogou_snippet(node: html.HtmlElement, title: str) -> str:
    """从搜狗结果块中挑出最像摘要的一段文本。"""
    # 从搜狗结果节点里筛选最适合作为摘要的文本片段。
    candidates: list[str] = []
    for text in node.xpath(
        ".//p//text() | .//div[contains(@class,'space-txt')]//text() | .//div[contains(@class,'fz-mid')]//text()"
    ):
        normalized = normalize_text(text)
        if not normalized or normalized == title:
            continue
        if len(normalized) < 12:
            continue
        candidates.append(normalized)
    return max(candidates, key=len, default="")


def parse_sogou_html_results(page_text: str, *, max_results: int) -> list[SearchResult]:
    """解析搜狗搜索页并提取标题、链接和摘要。"""
    # 从搜狗搜索结果页中提取结构化的标题、链接和摘要。
    tree = html.fromstring(page_text)
    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for title_node in tree.xpath("//h3[.//a[@href]]"):
        container = title_node.getparent()
        if container is None:
            container = title_node
        title = normalize_text("".join(title_node.xpath(".//text()")))
        url = normalize_result_url(
            title_node.xpath("string(.//a/@href)"),
            base_url="https://www.sogou.com",
        )
        if not title or not url:
            continue

        dedup_key = url.rstrip("/").lower()
        if dedup_key in seen_urls:
            continue
        seen_urls.add(dedup_key)

        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=_pick_sogou_snippet(container, title),
                source=extract_source(url),
                rank=len(results) + 1,
            )
        )
        if len(results) >= max_results:
            break

    return results


async def search_duckduckgo_html(query: str, *, max_results: int) -> list[SearchResult]:
    """使用 DuckDuckGo HTML 端点进行联网搜索并返回解析后的结果。"""
    # 通过 DuckDuckGo HTML 接口发起搜索并解析结果。
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=settings.search_timeout_seconds,
    ) as client:
        response = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": settings.search_region},
        )
        response.raise_for_status()

    if is_duckduckgo_anomaly_page(response.text):
        raise WorkflowError("DuckDuckGo 返回反爬挑战页")

    return parse_duckduckgo_html_results(response.text, max_results=max_results)


async def search_sogou_html(query: str, *, max_results: int) -> list[SearchResult]:
    """使用搜狗网页搜索作为 DuckDuckGo 失效时的兜底入口。"""
    # 通过搜狗网页搜索获取结果，作为主搜索源的兜底方案。
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=settings.search_timeout_seconds,
    ) as client:
        response = await client.get(
            "https://www.sogou.com/web",
            params={"query": query},
        )
        response.raise_for_status()

    return parse_sogou_html_results(response.text, max_results=max_results)


async def search_web(
    query: str, *, max_results: int | None = None
) -> list[SearchResult]:
    """对外统一的搜索入口：归一化 query，并按配置选择搜索 provider。"""
    # 按配置选择搜索提供方并返回统一结构的搜索结果。
    normalized_query = normalize_text(query)
    if not normalized_query:
        return []

    limit = normalize_search_limit(max_results)
    provider = settings.search_provider

    if provider == "duckduckgo_html":
        try:
            results = await search_duckduckgo_html(normalized_query, max_results=limit)
        except Exception:
            results = []
        return results or await search_sogou_html(normalized_query, max_results=limit)

    if provider == "sogou_html":
        return await search_sogou_html(normalized_query, max_results=limit)

    raise WorkflowError(f"不支持的搜索提供方: {provider}")
