from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from conf.db_conf import engine
from conf.logging_conf import app_logger, setup_logger
from conf.settings import settings
from routers import task_router
from utils.exceptions import AppError
from utils.response import error_response, success_response
from utils.runtime import ensure_runtime_directories


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logger()
    ensure_runtime_directories()
    app_logger.bind(module="system").info("application start")
    try:
        yield

    finally:
        app_logger.bind(module="system").info("application shutdown")
        logger_complete = app_logger.complete()
        if logger_complete:
            await logger_complete
        await engine.dispose()



app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
    description="轻量状态驱动 Agent：自然语言输入 -> Agent Loop -> 结构化整理 -> Excel 导出",
    version="0.1.0",
)
app.include_router(task_router, prefix=settings.api_prefix)


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError):
    return error_response(
        message=str(exc),
        data=exc.to_error_data(),
        status_code=getattr(exc, "status_code", 400) or 400,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    return error_response(message="请求参数校验失败", data=exc.errors(), status_code=422)


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception):
    return error_response(message=f"服务内部异常: {exc}", status_code=500)


@app.get("/")
async def root():
    return success_response(
        message="AI Agent service is running",
        data={
            "env": settings.app_env,
            "api_prefix": settings.api_prefix,
            "router_status": "mounted",
        },
    )


@app.get("/health")
async def health_check():
    return success_response(message="ok", data={"status": "healthy"})
