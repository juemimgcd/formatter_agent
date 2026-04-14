import pytest

from schemas import SearchResult
from utils import search_client
from utils.search_client import parse_duckduckgo_html_results, parse_sogou_html_results


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


@pytest.mark.asyncio
async def test_search_web_falls_back_to_sogou_when_duckduckgo_returns_empty(monkeypatch):
    monkeypatch.setattr(search_client.settings, "search_provider", "duckduckgo_html")

    async def fake_search_duckduckgo_html(query, *, max_results):
        return []

    async def fake_search_sogou_html(query, *, max_results):
        return [
            SearchResult(
                title="唐诗三百首",
                url="https://www.sogou.com/link?url=abc123",
                snippet="摘要",
                source="sogou.com",
                rank=1,
            )
        ]

    monkeypatch.setattr(
        search_client, "search_duckduckgo_html", fake_search_duckduckgo_html
    )
    monkeypatch.setattr(search_client, "search_sogou_html", fake_search_sogou_html)

    results = await search_client.search_web("唐诗三百首", max_results=5)

    assert len(results) == 1
    assert results[0].source == "sogou.com"
