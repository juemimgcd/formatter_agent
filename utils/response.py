from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask, BackgroundTasks

from schemas import ApiResponse


def success_response(
    message: str = "success",
    data: Any = None,
    status_code: int = 200,
    background: BackgroundTask | BackgroundTasks | None = None,
) -> JSONResponse:
    """返回统一的成功响应。"""

    payload = ApiResponse(success=True, message=message, data=data)
    return JSONResponse(
        content=jsonable_encoder(payload),
        status_code=status_code,
        background=background,
    )


def error_response(
    message: str = "error", data: Any = None, status_code: int = 400
) -> JSONResponse:
    """返回统一的失败响应。"""

    payload = ApiResponse(success=False, message=message, data=data)
    return JSONResponse(content=jsonable_encoder(payload), status_code=status_code)
