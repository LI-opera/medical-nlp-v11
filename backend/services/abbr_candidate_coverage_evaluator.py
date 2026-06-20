import json
import os
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ENV_PATH = os.path.join(BACKEND_DIR, ".env")

load_dotenv(ENV_PATH, override=True)

class ABBRCandidateCoverageEvaluator:
    #医学缩写候选覆盖度评估器
    #作用：判断候选集中是否存在一个能被当前上下文支持的合理扩写
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
    
    def evaluate(self,original_text:str,abbreviation:str,candidates:list[dict]):
        prompt = f"""
        You are a medical abbreviation candidate coverage evaluator.

        Task:
        Determine whether the provided candidate expansions contain at least one reasonable meaning for the abbreviation in the given clinical context.

        Clinical text:
        {original_text}

        Abbreviation:
        {abbreviation}

        Candidate expansions:
        {json.dumps(candidates, ensure_ascii=False, indent=2)}

        Important distinction:
        - Coverage evaluation asks: "Is there at least one reasonable candidate in this candidate set?"
        - It does NOT need to perform final expansion.
        - It should not rewrite the clinical text.

        Rules:
        1. If at least one candidate is contextually plausible, set coverage_ok to true.
        2. If none of the candidates fit the clinical context, set coverage_ok to false.
        3. If candidates are empty, set coverage_ok to false.
        4. If the context is insufficient but candidates contain common meanings, set coverage_ok to true with lower confidence.
        5. Do not invent new candidate expansions.
        6. Return only valid JSON.
        7. Do not use markdown.

        Return JSON in exactly this format:
        {{
        "abbreviation": "{abbreviation}",
        "coverage_ok": true,
        "confidence": 0.0,
        "plausible_candidates": [
            "candidate expansion here"
        ],
        "reason": "brief explanation",
        "issues": []
        }}
        """
        response = self.llm.invoke(prompt)
        content = response.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return{
                "abbreviation": abbreviation,
                "coverage_ok": False,
                "confidence": 0.0,
                "plausible_candidates": [],
                "reason": "Coverage evaluator did not return valid JSON.",
                "issues": ["invalid_json"],
                "raw_output": content
            }
        return parsed