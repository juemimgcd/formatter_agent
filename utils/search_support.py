from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

import httpx

from conf.settings import settings

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
}
MAX_SEARCH_RESULTS = 10
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_PARAMS = {
    "fbclid",
    "from",
    "gclid",
    "msclkid",
    "ref",
    "refer",
    "source",
    "spm",
    "src",
    "yclid",
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def extract_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host or "web"


def normalize_search_limit(max_results: int | None) -> int:
    limit = int(max_results or settings.search_result_limit)
    return max(1, min(MAX_SEARCH_RESULTS, limit))


def normalize_result_url(url: str, *, base_url: str) -> str:
    return normalize_text(urljoin(base_url, url))


def build_search_http_client() -> httpx.AsyncClient:
    options = {
        "headers": DEFAULT_HEADERS,
        "follow_redirects": True,
        "timeout": settings.search_timeout_seconds,
        "trust_env": settings.search_trust_env,
    }
    if settings.search_proxy_url:
        options["proxy"] = settings.search_proxy_url
    return httpx.AsyncClient(**options)


def canonicalize_search_url(url: str) -> str:
    normalized_url = normalize_text(url)
    if not normalized_url:
        return ""
    parsed = urlsplit(normalized_url)
    if not parsed.scheme or not parsed.netloc:
        return normalized_url.rstrip("/").lower()

    scheme = "https" if parsed.scheme in {"http", "https"} else parsed.scheme.lower()
    host = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered_key = key.lower()
        if lowered_key in TRACKING_QUERY_PARAMS:
            continue
        if any(lowered_key.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, value))

    query = urlencode(sorted(query_items), doseq=True)
    return urlunsplit((scheme, host, path, query, ""))
