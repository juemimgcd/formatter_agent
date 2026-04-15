from functools import lru_cache

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from conf.settings import settings
from utils.exceptions import ExtractionError


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    """获取并缓存用于结构化抽取的 LLM 客户端。

    该函数基于配置创建 OpenAI Compatible 的 `ChatOpenAI` 实例，并通过 LRU 缓存
    复用连接参数，避免在一次任务流程中重复初始化。

    Raises:
        ExtractionError: 未配置 `DASHSCOPE_API_KEY`（或对应的兼容 API Key）时抛出。
    """
    # 按当前配置创建并缓存结构化抽取阶段复用的 LLM 客户端。
    if not settings.dashscope_api_key:
        raise ExtractionError("DASHSCOPE_API_KEY 未配置，无法执行结构化抽取")

    return ChatOpenAI(
        model=settings.llm_model_name,
        api_key=SecretStr(settings.dashscope_api_key),
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=max(0, settings.llm_max_retries),
    )
