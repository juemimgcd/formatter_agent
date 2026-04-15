from pathlib import Path

import pandas as pd

from conf.settings import settings
from schemas import StructuredResultItem
from utils.excel_service import export_results_to_excel


def _result(*, title: str, score: int) -> StructuredResultItem:
    return StructuredResultItem(
        query="AI 产品经理",
        title=title,
        source="web",
        url=f"https://example.com/{title}",
        content_type="article",
        region="上海",
        role_direction="产品",
        summary=f"{title} 的结构化摘要，长度足够用于预览断言。",
        quality_score=score,
        extraction_notes=f"note-{title}",
    )


def test_export_results_to_excel_creates_file(test_output_dir, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", test_output_dir)

    excel_path = export_results_to_excel(
        [_result(title="first", score=91), _result(title="second", score=77)],
        filename="result.xlsx",
    )

    assert Path(excel_path).exists()


def test_export_results_to_excel_preserves_expected_columns(
    test_output_dir, monkeypatch
):
    monkeypatch.setattr(settings, "output_dir", test_output_dir)

    excel_path = export_results_to_excel([_result(title="first", score=91)])

    dataframe = pd.read_excel(excel_path, engine="openpyxl")

    assert list(dataframe.columns) == [
        "query",
        "title",
        "source",
        "url",
        "content_type",
        "region",
        "role_direction",
        "summary",
        "quality_score",
        "extraction_notes",
    ]
