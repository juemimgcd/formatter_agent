from datetime import datetime
import re
from pathlib import Path

import pandas as pd

from conf.settings import settings
from schemas import StructuredResultItem
from utils.exceptions import ExcelExportError

EXCEL_COLUMNS = [
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

def build_excel_filename(query: str) -> str:
    """根据查询主题生成导出文件名。"""

    sanitized = re.sub(r"[\\/:*?\"<>|]", "_", query).strip()
    sanitized = re.sub(r"\s+", "_", sanitized)
    if not sanitized:
        sanitized = "structured_search"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"structured_search_result_{sanitized}_{ts}.xlsx"


def export_results_to_excel(items: list[StructuredResultItem], filename: str | None = None) -> str:
    """把结果写入 Excel 文件并返回最终路径。"""

    output_dir = settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    final_name = filename or build_excel_filename(items[0].query if items else "structured_search")
    output_path = Path(output_dir) / final_name

    try:
        rows = [item.model_dump(mode="json") for item in items]
        dataframe = pd.DataFrame(rows, columns=EXCEL_COLUMNS)
        dataframe.to_excel(output_path, index=False, engine="openpyxl")
        return str(output_path.resolve())
    except Exception as exc:
        raise ExcelExportError(f"Excel 导出失败: {exc}") from exc
