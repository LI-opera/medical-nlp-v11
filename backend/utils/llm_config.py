from dataclasses import dataclass
from enum import Enum


class LLMProvider(str, Enum):
    """LLM provider options."""

    DEEPSEEK = "deepseek"
    QWEN = "qwen"


@dataclass
class LLMConfig:
    """LLM configuration. API keys are read by the factory from environment."""

    provider: LLMProvider = LLMProvider.DEEPSEEK
    model_name: str = "deepseek-chat"
    temperature: float = 0.0
    max_retries: int = 2


DEEPSEEK_CONFIG = LLMConfig(
    provider=LLMProvider.DEEPSEEK,
    model_name="deepseek-chat",
)

QWEN_CONFIG = LLMConfig(
    provider=LLMProvider.QWEN,
    model_name="qwen3.6-plus",
)
