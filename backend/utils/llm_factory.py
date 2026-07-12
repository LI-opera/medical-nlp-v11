import os
import time

from utils.llm_config import LLMConfig, LLMProvider
from utils.structured_logger import exc_meta, log_dependency


QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def create_llm(config: LLMConfig):
    """Create a chat LLM from config. Currently supports DeepSeek and Qwen."""
    start = time.perf_counter()
    log_dependency(
        "dependency.llm.config_check",
        component="llm_factory",
        provider=str(config.provider),
        model_name=config.model_name,
        ok=True,
    )
    if config.provider == LLMProvider.DEEPSEEK:
        from langchain_deepseek import ChatDeepSeek

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            log_dependency(
                "dependency.llm.config_error",
                component="llm_factory",
                provider=str(config.provider),
                model_name=config.model_name,
                missing_env="DEEPSEEK_API_KEY",
                ok=False,
                level="ERROR",
            )
            raise ValueError("DEEPSEEK_API_KEY is not set.")
        llm = ChatDeepSeek(
            model=config.model_name,
            api_key=api_key,
            temperature=config.temperature,
            max_retries=config.max_retries,
        )
        log_dependency(
            "dependency.llm.create_ok",
            component="llm_factory",
            provider=str(config.provider),
            model_name=config.model_name,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            ok=True,
        )
        return llm

    if config.provider == LLMProvider.QWEN:
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            log_dependency(
                "dependency.llm.config_error",
                component="llm_factory",
                provider=str(config.provider),
                model_name=config.model_name,
                missing_env="DASHSCOPE_API_KEY",
                ok=False,
                level="ERROR",
            )
            raise ValueError("DASHSCOPE_API_KEY is not set.")
        llm = ChatOpenAI(
            model=config.model_name,
            api_key=api_key,
            base_url=QWEN_BASE_URL,
            temperature=config.temperature,
            max_retries=config.max_retries,
        )
        log_dependency(
            "dependency.llm.create_ok",
            component="llm_factory",
            provider=str(config.provider),
            model_name=config.model_name,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            ok=True,
        )
        return llm

    try:
        raise ValueError(f"Unsupported LLM provider: {config.provider}")
    except ValueError as exc:
        log_dependency(
            "dependency.llm.config_error",
            component="llm_factory",
            provider=str(config.provider),
            model_name=config.model_name,
            ok=False,
            level="ERROR",
            **exc_meta(exc),
        )
        raise
