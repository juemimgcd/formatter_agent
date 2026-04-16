import pytest

from schemas import SearchResult
from utils.exceptions import WorkflowError
from utils import search_client
from utils.search_client import (
    get_search_provider_names,
    parse_bing_html_results,
    parse_duckduckgo_html_results,
    parse_sogou_html_results,
)


def test_parse_duckduckgo_html_results_extracts_unique_results():
    sample_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <h2 class="result__title">
            <a class="result__a" href="https://example.com/a">Title A</a>
          </h2>
          <a class="result__url" href="https://example.com/a">example.com/a</a>
          <a class="result__snippet">Snippet A</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <h2 class="result__title">
            <a class="result__a" href="https://example.com/a/">Title A Dup</a>
          </h2>
          <a class="result__snippet">Snippet Dup</a>
        </div>
        <div class="result results_links results_links_deep web-result">
          <h2 class="result__title">
            <a class="result__a" href="https://github.com/openai/openai-python">Title B</a>
          </h2>
          <a class="result__snippet">Snippet B</a>
        </div>
      </body>
    </html>
    """

    results = parse_duckduckgo_html_results(sample_html, max_results=5)

    assert len(results) == 2
    assert results[0].title == "Title A"
    assert results[0].url == "https://example.com/a"
    assert results[0].snippet == "Snippet A"
    assert results[0].source == "example.com"
    assert results[1].source == "github.com"


def test_parse_bing_html_results_extracts_results():
    sample_html = """
    <html>
      <body>
        <li class="b_algo">
          <h2><a href="https://example.com/zhang-yimou">张艺谋作品全集</a></h2>
          <p>整理张艺谋导演作品、监制作品和主要获奖信息。</p>
        </li>
      </body>
    </html>
    """

    results = parse_bing_html_results(sample_html, max_results=5)

    assert len(results) == 1
    assert results[0].title == "张艺谋作品全集"
    assert results[0].url == "https://example.com/zhang-yimou"
    assert results[0].snippet == "整理张艺谋导演作品、监制作品和主要获奖信息。"
    assert results[0].source == "example.com"


def test_is_bing_captcha_page_detects_challenge_page():
    sample_html = """
    <html>
      <body>
        <div class="captcha">
          <p>To continue, please type the characters below.</p>
        </div>
      </body>
    </html>
    """

    assert search_client.is_bing_captcha_page(sample_html) is True


def test_parse_sogou_html_results_extracts_results():
    sample_html = """
    <html>
      <body>
        <div class="struct201102">
          <h3 class="vr-title">
            <a href="/link?url=abc123"><em>唐诗三百首</em>_全集赏析</a>
          </h3>
          <div class="fz-mid space-txt">熟读唐诗三百首，不会作诗也会吟。</div>
        </div>
      </body>
    </html>
    """

    results = parse_sogou_html_results(sample_html, max_results=5)

    assert len(results) == 1
    assert results[0].title == "唐诗三百首_全集赏析"
    assert results[0].url == "https://www.sogou.com/link?url=abc123"
    assert results[0].snippet == "熟读唐诗三百首，不会作诗也会吟。"
    assert results[0].source == "sogou.com"


def test_get_search_provider_names_uses_only_duck_bing_and_sogou():
    assert get_search_provider_names("auto") == [
        "duckduckgo_html",
        "bing_html",
        "sogou_html",
    ]
    assert get_search_provider_names("duckduckgo_html") == ["duckduckgo_html"]
    assert get_search_provider_names("bing_html") == ["bing_html"]
    assert get_search_provider_names("sogou_html") == ["sogou_html"]
    assert get_search_provider_names("baidu_html") == []
    assert get_search_provider_names("serper_api") == []


@pytest.mark.asyncio
async def test_search_web_auto_tries_duck_bing_then_sogou(monkeypatch):
    monkeypatch.setattr(search_client.settings, "search_provider", "auto")

    called_providers: list[str] = []

    async def fake_search_duckduckgo_html(query, *, max_results):
        called_providers.append("duckduckgo_html")
        return []

    async def fake_search_bing_html(query, *, max_results):
        called_providers.append("bing_html")
        raise TimeoutError()

    async def fake_search_sogou_html(query, *, max_results):
        called_providers.append("sogou_html")
        return [
            SearchResult(
                title="张艺谋作品全集",
                url="https://www.sogou.com/link?url=abc123",
                snippet="摘要",
                source="sogou.com",
                rank=1,
            )
        ]

    monkeypatch.setattr(
        search_client, "search_duckduckgo_html", fake_search_duckduckgo_html
    )
    monkeypatch.setattr(search_client, "search_bing_html", fake_search_bing_html)
    monkeypatch.setattr(search_client, "search_sogou_html", fake_search_sogou_html)

    results = await search_client.search_web("张艺谋作品全集", max_results=5)

    assert len(results) == 1
    assert results[0].source == "sogou.com"
    assert called_providers == [
        "duckduckgo_html",
        "bing_html",
        "sogou_html",
    ]


@pytest.mark.asyncio
async def test_explicit_provider_does_not_chain_other_engines(monkeypatch):
    monkeypatch.setattr(search_client.settings, "search_provider", "duckduckgo_html")

    async def fake_search_duckduckgo_html(query, *, max_results):
        raise TimeoutError()

    async def fake_search_bing_html(query, *, max_results):
        raise AssertionError("explicit duckduckgo_html should not call bing_html")

    monkeypatch.setattr(
        search_client, "search_duckduckgo_html", fake_search_duckduckgo_html
    )
    monkeypatch.setattr(search_client, "search_bing_html", fake_search_bing_html)

    with pytest.raises(WorkflowError) as exc_info:
        await search_client.search_web("接口压测", max_results=5)

    error_message = str(exc_info.value)
    assert "duckduckgo_html failed: TimeoutError" in error_message
    assert "bing_html" not in error_message


@pytest.mark.asyncio
async def test_search_web_rejects_baidu_and_professional_api_providers(monkeypatch):
    monkeypatch.setattr(search_client.settings, "search_provider", "baidu_html")
    with pytest.raises(WorkflowError) as baidu_exc_info:
        await search_client.search_web("张艺谋作品全集", max_results=5)

    monkeypatch.setattr(search_client.settings, "search_provider", "serper_api")
    with pytest.raises(WorkflowError) as api_exc_info:
        await search_client.search_web("张艺谋作品全集", max_results=5)

    assert "不支持的搜索提供方: baidu_html" in str(baidu_exc_info.value)
    assert "不支持的搜索提供方: serper_api" in str(api_exc_info.value)
