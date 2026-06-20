import json
import os
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ENV_PATH = os.path.join(BACKEND_DIR, ".env")

load_dotenv(ENV_PATH, override=True)

class ABBRCandidateFallbackRetriever:
    #缩写候选兜底召回器。
    #作用:当本地候选库没有找到缩写对应的扩写词时，让LLM只生成候选扩写词列表，不直接改写原句。
    def __init__(self):
        #初始化llm模型
        api_key = os.getenv("DEEPSEEK_API_KEY")

        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set.")

        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=api_key.strip(),
            temperature=0,
            max_retries=2
        )

    def retrieve(self,abbreviation:str,context_text:str):
        prompt = f"""
        You are a medical abbreviation candidate retrieval assistant.

        Task:
        Generate possible medical expansion candidates for the abbreviation based on the clinical context.

        Clinical text:`
        {context_text}

        Abbreviation:
        {abbreviation}

        Important:
        You are NOT expanding the full clinical sentence.
        You are only generating candidate expansions for the abbreviation.

        Rules:
        1. Return possible medical expansions for the abbreviation.
        2. Prefer expansions that are plausible in the given clinical context.
        3. Do not rewrite the clinical text.
        4. Do not add diagnoses, treatments, symptoms, or assumptions.
        5. If the abbreviation is unclear, return multiple candidates with low confidence.
        6. If the abbreviation is not a recognized or plausible medical abbreviation in the given context, return an empty candidates list.
        7. Do not create expansions by combining words that merely start with the same letters.
        8. Do not invent rare, artificial, or unsupported expansions.
        9. Only return candidates that are commonly used medical abbreviations or strongly supported by the clinical context.
        10. Return only valid JSON.
        11. Do not use markdown.

        Return JSON in exactly this format:
        {{
        "abbreviation": "{abbreviation}",
        "candidates": [
            {{
            "abbreviation": "{abbreviation}",
            "expansion": "candidate expansion here",
            "source": "fallback_llm",
            "confidence": 0.0
            }}
        ],
        "reason": "brief explanation"
        }}
        """
        
        response = self.llm.invoke(prompt)

        content = response.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {
                "abbreviation": abbreviation,
                "candidates": [],
                "reason": "Fallback retriever did not return valid JSON.",
                "raw_output": content
            }
        return parsed