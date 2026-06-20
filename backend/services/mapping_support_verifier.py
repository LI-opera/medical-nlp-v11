import json
import os
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from pydantic import BaseModel, Field


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ENV_PATH = os.path.join(BACKEND_DIR, ".env")

load_dotenv(ENV_PATH, override=True)


MAPPING_SUPPORT_SYSTEM_PROMPT = """
You are a clinical abbreviation mapping support verifier.

Your task is NOT to decide whether an expansion is medically valid in general.

Your task is to decide whether the given clinical text provides enough contextual evidence
to support the specific abbreviation-to-expansion mapping.

You must be conservative.

If the abbreviation has a possible medical expansion, but the surrounding text does not provide
enough clinical context to support that expansion, mark supported as false.

Return only valid JSON.
Do not use markdown.
"""


class MappingSupportResult(BaseModel):
    """
    当前文本是否支持 abbreviation -> expansion 这个映射。
    """
    supported: bool = Field(description="当前文本是否支持该缩写扩写")
    confidence: float = Field(description="支持判断的置信度，0 到 1")
    reason: str = Field(description="判断原因")


class MappingSupportVerifier:
    """
    Mapping Support Verifier

    作用：
    判断当前 clinical text 是否真的支持某个 abbreviation -> expansion。

    注意：
    它不是判断 expansion 是否医学上存在。
    它判断的是：
    当前这句话里有没有足够上下文支持这个 expansion。
    """

    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set.")

        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=api_key.strip(),
            temperature=0,
            max_retries=2
        )

    def verify(
        self,
        text: str,
        abbreviation: str,
        expansion: str
    ) -> MappingSupportResult:
        prompt = f"""
{MAPPING_SUPPORT_SYSTEM_PROMPT}

Clinical text:
{text}

Abbreviation:
{abbreviation}

Candidate expansion:
{expansion}

Question:
Does the clinical text provide enough contextual evidence to support this abbreviation-to-expansion mapping?

Important distinction:
- If the expansion is medically valid in general but not supported by the current text, return supported=false.
- If the text is too short or too generic, return supported=false.
- If there are clear context clues supporting the expansion, return supported=true.
- Do not rely only on the abbreviation itself.
- Be conservative.

Return JSON in exactly this format:
{{
  "supported": false,
  "confidence": 0.0,
  "reason": "brief explanation"
}}
"""

        response = self.llm.invoke(prompt)
        content = response.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(content)
            return MappingSupportResult(
                supported=parsed.get("supported", False),
                confidence=float(parsed.get("confidence", 0.0)),
                reason=parsed.get("reason", "")
            )
        except Exception:
            return MappingSupportResult(
                supported=False,
                confidence=0.0,
                reason=f"MappingSupportVerifier did not return valid JSON. Raw output: {content}"
            )