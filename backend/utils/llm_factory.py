import os

from utils.llm_config import LLMConfig, LLMProvider


QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def create_llm(config: LLMConfig):
    """Create a chat LLM from config. Currently supports DeepSeek and Qwen."""
    if config.provider == LLMProvider.DEEPSEEK:
        from langchain_deepseek import ChatDeepSeek

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set.")
        return ChatDeepSeek(
            model=config.model_name,
            api_key=api_key,
            temperature=config.temperature,
            max_retries=config.max_retries,
        )

    if config.provider == LLMProvider.QWEN:
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY is not set.")
        return ChatOpenAI(
            model=config.model_name,
            api_key=api_key,
            base_url=QWEN_BASE_URL,
            temperature=config.temperature,
            max_retries=config.max_retries,
        )

    raise ValueError(f"Unsupported LLM provider: {config.provider}")
