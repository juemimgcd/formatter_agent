from typing import Any

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):

    success: bool = Field(default=True, description="接口是否执行成功。成功时为 true，失败时为 false。")
    message: str = Field(default="ok", description="给调用方看的提示信息，用来说明当前结果或错误原因。")
    data: Any | None = Field(default=None, description="真正的业务数据载荷。没有业务数据时可以为空。")


class ErrorData(BaseModel):
    code: str
    details: Any | None = None
