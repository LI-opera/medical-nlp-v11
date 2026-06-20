import json
import os
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

#绝对路径，引入环境变量
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ENV_PATH = os.path.join(BACKEND_DIR, ".env")

load_dotenv(ENV_PATH, override=True)

class ABBRReflectionService:
    """
    医学缩写扩展反思修正服务。
    作用：当Verifier认为扩写不可靠时，根据原始文本，上一次扩写结果，校验问题，让LLM重新生成
    """
    def __init__(self):
        #获得llm api
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set.")
        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=api_key.strip(),
            temperature=0,
            max_retries=2
        )
    
    def reflect(self,original_text:str,previous_expanded_text:str,verification:dict,abbreviation_candidates:list[dict]):
        #根据verifier的错误报告重新扩写
        prompt = f"""
        You are a medical abbreviation reflection assistant.

        Task:
        Revise the expanded clinical text based on the verification feedback.

        Original clinical text:
        {original_text}

        Previous expanded clinical text:
        {previous_expanded_text}

        Verification feedback:
        {json.dumps(verification, ensure_ascii=False, indent=2)}

        Available abbreviation candidates:
        {json.dumps(abbreviation_candidates, ensure_ascii=False, indent=2)}

        Rules:
        1. Only expand medical abbreviations.
        2. Do not add new symptoms, diagnoses, treatments, or assumptions.
        3. Preserve negation, uncertainty, severity, timing, and clinical meaning.
        4. If an abbreviation is ambiguous, choose the meaning best supported by the original context.
        5. Return only valid JSON.
        6. Do not include markdown.
        7. When revising mappings, choose expansions from the available abbreviation candidates when possible.
        8. Do not invent a new expansion if a candidate exists for that abbreviation.

        Return JSON in exactly this format:
        {{
        "revised_expanded_text": "revised clinical text here",
        "revised_mappings": [
           {{
            "abbreviation": "SOB",
            "expansion": "shortness of breath"
            }}
        ],
        "reason": "brief explanation of what was corrected"
        }}
        """

        response = self.llm.invoke(prompt)
        content = response.content.strip()
        #取出content json文本中的杂质
        content = content.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return{
                "revised_expanded_text": previous_expanded_text,
                "revised_mappings": [],
                "reason": "Reflection did not return valid JSON.",
                "raw_output": content
            }