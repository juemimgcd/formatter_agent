from __future__ import annotations

import re
from urllib.parse import urljoin
from urllib.parse import urlparse

import httpx
from lxml import html

from conf.settings import settings
from schemas.search_schema import SearchResult
from utils.exceptions import WorkflowError, format_exception

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
}
MAX_SEARCH_RESULTS = 10
DEFAULT_SEARCH_PROVIDER_ORDER = ["duckduckgo_html", "bing_html", "sogou_html"]
SEARCH_PROVIDER_NAMES = set(DEFAULT_SEARCH_PROVIDER_ORDER)


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


def build_search_http_client() -> httpx.AsyncClient:
    """创建搜索请求使用的 HTTP 客户端。"""
    # 支持显式代理配置，解决 Celery 进程无法读取系统代理导致的 TLS 连接失败。
    client_options = {
        "headers": DEFAULT_HEADERS,
        "follow_redirects": True,
        "timeout": settings.search_timeout_seconds,
        "trust_env": settings.search_trust_env,
    }
    if settings.search_proxy_url:
        client_options["proxy"] = settings.search_proxy_url
    return httpx.AsyncClient(**client_options)


def build_search_result(
    *,
    title: str,
    url: str,
    snippet: str,
    rank: int,
) -> SearchResult | None:
    """构造统一搜索结果，缺少标题或 URL 时返回 None。"""
    # 三个 HTML provider 最终都收敛到同一个 SearchResult。
    normalized_title = normalize_text(title)
    normalized_url = normalize_text(url)
    if not normalized_title or not normalized_url:
        return None
    return SearchResult(
        title=normalized_title,
        url=normalized_url,
        snippet=normalize_text(snippet),
        source=extract_source(normalized_url),
        rank=rank,
    )


def deduplicate_search_results(items: list[SearchResult]) -> list[SearchResult]:
    """按 URL 去重搜索结果并重新排列 rank。"""
    # 不同搜索页可能返回重复链接，这里保留首次出现的结果。
    deduplicated: list[SearchResult] = []
    seen_urls: set[str] = set()
    for item in items:
        normalized_url = item.url.rstrip("/").lower()
        if not normalized_url or normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        deduplicated.append(item.model_copy(update={"rank": len(deduplicated) + 1}))
    return deduplicated


def parse_duckduckgo_html_results(
    page_text: str, *, max_results: int
) -> list[SearchResult]:
    """解析 DuckDuckGo HTML 搜索页，提取结果列表。"""
    # 从 DuckDuckGo 的 HTML 页面中解析出结构化搜索结果。
    results: list[SearchResult] = []

    for node in html.fromstring(page_text).xpath(
        "//div[contains(@class, 'web-result')]"
    ):
        result = build_search_result(
            title="".join(node.xpath(".//a[contains(@class, 'result__a')]//text()")),
            url=node.xpath("string(.//a[contains(@class, 'result__a')]/@href)"),
            snippet=" ".join(
                node.xpath(".//*[contains(@class, 'result__snippet')]//text()")
            ),
            rank=len(results) + 1,
        )
        if result is not None:
            results.append(result)
        if len(results) >= max_results:
            break

    return deduplicate_search_results(results)


def is_duckduckgo_anomaly_page(page_text: str) -> bool:
    """判断 DuckDuckGo 是否返回了反爬挑战页。"""
    # 检测返回页面是否属于 DuckDuckGo 的异常或反爬响应。
    lowered = page_text.lower()
    return "anomaly.js" in lowered or 'id="challenge-form"' in lowered


def parse_bing_html_results(page_text: str, *, max_results: int) -> list[SearchResult]:
    """解析 Bing 搜索页并提取标题、链接和摘要。"""
    # 从 Bing 的常见 b_algo 结果块中解析结构化搜索结果。
    tree = html.fromstring(page_text)
    results: list[SearchResult] = []

    for node in tree.xpath("//li[contains(@class,'b_algo')][.//h2//a[@href]]"):
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
    """判断 Bing 是否返回验证码页。"""
    # Bing 在异常访问或风控时会返回 captcha 页面，此时不能当作空结果处理。
    lowered = page_text.lower()
    return "captcha" in lowered and "b_algo" not in lowered


def pick_sogou_snippet(node: html.HtmlElement, title: str) -> str:
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

    for title_node in tree.xpath("//h3[.//a[@href]]"):
        container = title_node.getparent()
        if container is None:
            container = title_node
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
    """使用 DuckDuckGo HTML 端点进行联网搜索并返回解析后的结果。"""
    # 通过 DuckDuckGo HTML 接口发起搜索并解析结果。
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
    """使用 Bing 搜索获取搜索结果。"""
    # Bing 结果页结构相对稳定，用作普通搜索引擎来源之一。
    async with build_search_http_client() as client:
        response = await client.get(
            "https://www.bing.com/search",
            params={"q": query},
        )
        response.raise_for_status()

    if is_bing_captcha_page(response.text):
        raise WorkflowError("Bing 返回验证码页")

    return parse_bing_html_results(response.text, max_results=max_results)


async def search_sogou_html(query: str, *, max_results: int) -> list[SearchResult]:
    """使用搜狗网页搜索获取搜索结果。"""
    # 搜狗适合作为中文查询的普通搜索引擎来源之一。
    async with build_search_http_client() as client:
        response = await client.get(
            "https://www.sogou.com/web",
            params={"query": query},
        )
        response.raise_for_status()

    return parse_sogou_html_results(response.text, max_results=max_results)


def get_search_provider_names(provider: str) -> list[str]:
    """根据配置返回本次搜索要尝试的 provider 顺序。"""
    # auto 只在 DuckDuckGo、Bing、搜狗之间切换；显式指定时只跑单个 provider。
    normalized_provider = normalize_text(provider).lower()
    if normalized_provider == "auto":
        return list(DEFAULT_SEARCH_PROVIDER_ORDER)
    if normalized_provider in SEARCH_PROVIDER_NAMES:
        return [normalized_provider]
    return []


async def run_search_provider(
    provider_name: str,
    query: str,
    *,
    max_results: int,
) -> list[SearchResult]:
    """执行指定搜索 provider 并返回统一搜索结果。"""
    # 将 provider 名称映射到具体搜索函数，避免 search_web 里堆太多分支。
    if provider_name == "duckduckgo_html":
        return await search_duckduckgo_html(query, max_results=max_results)
    if provider_name == "bing_html":
        return await search_bing_html(query, max_results=max_results)
    if provider_name == "sogou_html":
        return await search_sogou_html(query, max_results=max_results)
    raise WorkflowError(f"不支持的搜索提供方: {provider_name}")


async def search_web(
    query: str, *, max_results: int | None = None
) -> list[SearchResult]:
    """对外统一的搜索入口：归一化 query，并按配置选择搜索 provider。"""
    # 按配置选择搜索提供方并返回统一结构的搜索结果。
    normalized_query = normalize_text(query)
    if not normalized_query:
        return []

    limit = normalize_search_limit(max_results)
    provider_names = get_search_provider_names(settings.search_provider)
    if not provider_names:
        raise WorkflowError(f"不支持的搜索提供方: {settings.search_provider}")

    provider_errors: list[str] = []
    for provider_name in provider_names:
        try:
            results = await run_search_provider(
                provider_name,
                normalized_query,
                max_results=limit,
            )
        except Exception as exc:
            provider_errors.append(f"{provider_name} failed: {format_exception(exc)}")
            continue

        if results:
            return results

        provider_errors.append(f"{provider_name} returned empty result")

    raise WorkflowError("; ".join(provider_errors) or "all search providers failed")
