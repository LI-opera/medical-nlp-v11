# 批次 15 · 给 Codex 的指令(可整段复制)· LLM 配置 + 模型工厂(为异质 verify 铺地基)

## 背景与范围

照 `utils/embedding_config.py` + `utils/embedding_factory.py` 的写法,**新建一套 LLM 的配置 + 工厂**,让后面"按配置选不同模型"成为可能(这一批只铺地基,**不改 verify、不接线**)。两个现成配置:DeepSeek(`deepseek-chat`)+ 千问(DashScope)。两个 key 已在 `backend/.env`:`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`。

**铁律**:只**新增**两个文件,不动任何现有代码;不接线主链路(主 benchmark 自然不受影响)。

工作在 `medical-refactor`。

---

## A · 新建 `backend/utils/llm_config.py`(仿 embedding_config)

```python
# 声明 LLM 参数(仿 embedding_config 的写法)
from dataclasses import dataclass
from enum import Enum


class LLMProvider(str, Enum):
    """LLM 来源(固定字符串选项)。"""
    DEEPSEEK = "deepseek"
    QWEN = "qwen"            # 阿里通义千问,走 DashScope 兼容 OpenAI 接口


@dataclass
class LLMConfig:
    """LLM 配置类。密钥不写在这里,工厂运行时从 .env 读。"""
    provider: LLMProvider = LLMProvider.DEEPSEEK
    model_name: str = "deepseek-chat"
    temperature: float = 0.0
    max_retries: int = 2


# 两个现成配置(直接 import 用)
DEEPSEEK_CONFIG = LLMConfig(provider=LLMProvider.DEEPSEEK, model_name="deepseek-chat")
# ↓ 模型串按你指定的填;若 DashScope 报"模型不存在",改成你账号支持的(如 qwen-plus / qwen-max)
QWEN_CONFIG = LLMConfig(provider=LLMProvider.QWEN, model_name="qwen3.6-plus")
```

## B · 新建 `backend/utils/llm_factory.py`(仿 embedding_factory)

```python
# 根据配置真正创建 LLM(仿 embedding_factory 的 if-provider 分支)
import os

from utils.llm_config import LLMProvider, LLMConfig

# 千问 DashScope 的 OpenAI 兼容端点(用 ChatOpenAI 指过去,接口和 ChatDeepSeek 一致:.invoke().content)
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def create_llm(config: LLMConfig):
    """根据配置创建对应的 chat LLM。当前支持 DeepSeek / 千问,后面可加分支。"""
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
```

> 千问用 `langchain_openai.ChatOpenAI` 指到 DashScope 的兼容端点——这样它和 `ChatDeepSeek` **接口完全一致**(都 `.invoke(prompt).content`),下一批把 verify 换成它时一行不用改逻辑。若没装:`pip install langchain-openai --break-system-packages`。

---

## 验收

1. **编译 + import**:`python -m compileall backend/utils` 通过;`python -c "import sys;sys.path.append('backend');from utils.llm_factory import create_llm;from utils.llm_config import DEEPSEEK_CONFIG, QWEN_CONFIG;print('OK')"` → `OK`。
2. **两个模型都能真应答**(顺带验掉 key / 模型串对不对):
   ```bash
   python -c "import sys;sys.path.append('backend');from dotenv import load_dotenv;load_dotenv('backend/.env');from utils.llm_factory import create_llm;from utils.llm_config import DEEPSEEK_CONFIG,QWEN_CONFIG;print('DS:',create_llm(DEEPSEEK_CONFIG).invoke('reply with the single word: ok').content);print('QWEN:',create_llm(QWEN_CONFIG).invoke('reply with the single word: ok').content)"
   ```
   两行都打出回复 = 通。**若 QWEN 这行报"模型不存在/无效"**,把 `llm_config.py` 里 `QWEN_CONFIG` 的 `model_name` 改成你 DashScope 账号支持的(如 `qwen-plus`),再跑。
3. **没碰主链路**:确认只新增了 `utils/llm_config.py`、`utils/llm_factory.py` 两个文件,其它文件未动。
4. **判定**:1-3 全过 → 合入。

## 提交

```bash
git add backend/utils/llm_config.py backend/utils/llm_factory.py
git commit -m "V11 batch15: add LLM config + factory (mirror embedding pattern); DeepSeek + Qwen(DashScope) presets. Infra only, not wired yet."
```
> 这一批只铺地基。下一批:把 `abbr_verifier` 改成 `create_llm(指定配置)`,让 **coverage=DeepSeek(生成)/ verify=千问(异质检查)**,再用 concept bench + 主 bench 量"换异质判官"的净收益。
