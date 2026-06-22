import json
import os
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ENV_PATH = os.path.join(BACKEND_DIR,".env")

load_dotenv(ENV_PATH,override=True)

class ABBVerifier:
    """
    医学缩写扩展校验器：
    作用：判断LLM扩写后的文本是否保持愿意，并且是否能被后续SNOMED标准化结果支持
    """
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set.")
        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=api_key,
            temperature=0,
            #如果调用 DeepSeek API 失败，最多自动重试 2 次。
            max_retries=2
        )
    
    def verify(self,original_text:str,expanded_text:str,standardization:dict):
        #检验缩写扩展是否可信
        prompt = f"""
        You are a medical abbreviation verification assistant.

        Task:
        Verify whether the expanded clinical text correctly preserves the meaning of the original clinical text.

        Original clinical text:
        {original_text}

        Expanded clinical text:
        {expanded_text}

        SNOMED standardization candidates:
        {json.dumps(standardization.get("entities",[]), ensure_ascii=False, indent=2)}

        Evaluation criteria:
        1. The expanded text should only expand abbreviations.
        2. It should not add new diagnoses, symptoms, treatments, or assumptions.
        3. Each expanded medical term should be reasonable in the original context.
        4. The SNOMED candidates should generally support the expanded medical terms.
        5. If the expansion is uncertain, mark it as invalid.

        Return only valid JSON with these fields:

        - is_valid: boolean. True if the expanded text preserves the original meaning and only expands abbreviations. False otherwise.
        - confidence: number between 0 and 1. Higher means more confident.
        - reason: string. A brief explanation of the decision.
        - issues: list of strings. Empty list if no issues. Use issue labels such as:
        - "added_information"
        - "changed_meaning"
        - "unsupported_by_snomed"
        - "ambiguous_abbreviation"
        - "not_only_abbreviation_expansion"

        JSON format:
        {{
        "is_valid": true,
        "confidence": 0.0,
        "reason": "brief explanation",
        "issues": []
        }}
       
        """
        response = self.llm.invoke(prompt)
        content = response.content.strip()
        #尝试解析json
        try:
            #把 JSON 字符串转成 Python dict
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "is_valid": False,
                "confidence": 0.0,
                "reason": "Verifier did not return valid JSON.",
                "raw_output": content,
                "issues": ["invalid_json"]
            }
    
    def verify_mappings(
        self,
        original_text: str,
        expanded_text: str,
        mapping_standardizations: list[dict]
    ):
        """选择每个扩写最忠实的 SNOMED 标准化概念，或明确弃码。"""
        indexed_mappings = []
        for mapping in mapping_standardizations:
            indexed_mappings.append({
                "abbreviation": mapping.get("abbreviation"),
                "expansion": mapping.get("expansion"),
                "candidates": [
                    {"index": index, **candidate}
                    for index, candidate in enumerate(mapping.get("candidates") or [])
                ],
            })

        prompt = f"""
        You are a medical terminology grounding verifier.

        For each abbreviation mapping you are given the expansion and a SHORT LIST of
        candidate SNOMED concepts retrieved for that expansion. Each candidate has a
        zero-based index, concept_name, domain_id, and retrieval scores.

        Your job is NOT to re-judge whether the abbreviation expansion is correct.
        That decision has already been made by the abbreviation coverage stage.

        Your job is to pick which candidate concept is a FAITHFUL standardization of
        the expansion:

        - chosen_index must be the zero-based index of the candidate whose concept_name
          means the SAME clinical thing as the expansion.
        - chosen_index must be null if NONE of the candidates faithfully represents the
          expansion.
        - standardization_faithful must be true only when chosen_index points to a
          faithful candidate.
        - Judge concept_name against the expansion's clinical meaning. Do not trust the
          retrieval score by itself.
        - A finding or condition must not be grounded to a rating scale, measurement,
          procedure, or other related-but-different concept.
        - Example: "chest pain" and "Chest pain rating" are not the same clinical thing,
          so choose null unless another candidate faithfully represents chest pain.
        - Only choose among the supplied candidates. Never invent a concept.
        - Return exactly one mapping_validations item for each input mapping, in the
          same order.
        - Return raw valid JSON only. Do not use markdown.

        Original clinical text (context only):
        {original_text}

        Expanded clinical text (context only):
        {expanded_text}

        Abbreviation expansions and indexed SNOMED candidates:
        {json.dumps(indexed_mappings, ensure_ascii=False, indent=2)}

        Return JSON in exactly this structure:
        {{
          "mapping_validations": [
            {{
              "abbreviation": "CP",
              "expansion": "chest pain",
              "chosen_index": 0,
              "standardization_faithful": true,
              "reason": "brief explanation"
            }}
          ]
        }}
        """

        response = self.llm.invoke(prompt)
        content = response.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(content)
            mapping_validations = parsed.get("mapping_validations", [])
            return {
                "sentence_validity": {
                    "is_valid": True,
                    "confidence": 1.0,
                    "reason": "Expansion validity is decided upstream by coverage.",
                    "issues": []
                },
                "mapping_validations": mapping_validations,
                "overall_valid": len(mapping_validations) == len(mapping_standardizations)
            }
        except json.JSONDecodeError:
            return {
                "sentence_validity": {
                    "is_valid": True,
                    "confidence": 1.0,
                    "reason": "Expansion validity is decided upstream by coverage.",
                    "issues": []
                },
                "mapping_validations": [],
                "overall_valid": False,
                "raw_output": content
            }

"""
#######这个是句子间匹配的相似参数
扩写是否可信
"is_valid": true,
置信度
"confidence": 0.0,
可信的理由
"reason": "brief explanation",
有问题填到issues没有为空
"issues": []

###########这个是改写词间的匹配参数
所有改写词是否整体通过
overall_valid
items 表示逐个缩写的校验结果列表
abbreviation 原始缩写
expansion 扩写词汇
is_valid 当前这个缩写扩展是否可信
confidence 模型对这个判断的置信度
supported_by_snomed snomed是否支持这个expansion
reason 简短解释为什么这么判断
issues 问题标签列表
"""
