from __future__ import annotations

from typing import Any


class AppError(Exception):
    """项目内部的通用业务异常基类。

    提供：
    - `code`: 稳定错误码（便于调用方分支处理）
    - `status_code`: 建议的 HTTP 状态码（接口层可直接使用）
    - `data`: 可选上下文信息（需可序列化）

    兼容：`str(exc)` 返回对外 message。
    """

    default_code: str = "app_error"
    default_status_code: int = 400

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        data: Any | None = None,
        cause: Exception | None = None,
    ) -> None:
        """初始化业务异常对象并记录可序列化的上下文信息。

        Args:
            message: 对外可读的错误信息。
            code: 稳定错误码；为空则使用类默认值。
            status_code: 建议 HTTP 状态码；为空则使用类默认值。
            data: 额外上下文（需可 JSON 序列化）。
            cause: 原始异常（用于内部追踪）。
        """
        self.message = (message or "").strip() or "业务异常"
        self.code = (code or self.default_code).strip() or self.default_code
        self.status_code = (
            status_code if status_code is not None else self.default_status_code
        )
        self.data = data
        self.cause = cause
        super().__init__(self.message)

    def to_error_data(self) -> dict[str, Any] | None:
        """用于接口层包装时的 data 字段。

        默认返回 {"code": ..., "details": ...} 结构；若无额外信息则返回 None。
        """

        payload: dict[str, Any] = {"code": self.code}
        if self.data is not None:
            payload["details"] = self.data
        return payload if payload else None


class WorkflowError(AppError):
    """运行时初始化或任务编排阶段异常。"""

    default_code = "workflow_error"


class ExtractionError(AppError):
    """结构化抽取阶段异常。"""

    default_code = "extraction_error"
    default_status_code = 500


class ExcelExportError(AppError):
    """Excel 导出阶段异常。"""

    default_code = "excel_export_error"
    default_status_code = 500
