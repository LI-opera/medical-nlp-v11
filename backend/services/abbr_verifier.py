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
    
    def verify_mappings(self,original_text:str,expanded_text:str,mapping_standardizations:list[dict]):
        #逐个校验abbreviation->expansion是否合理,同时校验整句扩写是否保持原意
        prompt = f"""
        You are a medical abbreviation verification assistant.

        Task:
        Evaluate the abbreviation expansion result from two separate perspectives:

        1. Sentence-level validity:
        Check whether the expanded clinical text preserves the meaning of the original clinical text.

        2. Mapping-level validity:
        Check whether each abbreviation-expansion mapping is medically reasonable and supported by context and SNOMED candidates.

        Original clinical text:
        {original_text}

        Expanded clinical text:
        {expanded_text}

        Abbreviation mappings with SNOMED candidates:
        {json.dumps(mapping_standardizations, ensure_ascii=False, indent=2)}

        Important rules:
        - Evaluate sentence_validity separately from mapping_validations.
        - Do not merge the two judgments.
        - The number of mapping_validations must be exactly the same as the number of input abbreviation mappings.
        - A sentence can preserve meaning even if one mapping is uncertain.
        - A mapping can be medically plausible even if the sentence-level expansion changed wording incorrectly.
        - SNOMED candidates are supporting evidence, not final truth.
        - Do not invent new abbreviations, diagnoses, symptoms, treatments, or assumptions.
        - If uncertain, use low confidence and explain the issue.

        Sentence-level evaluation:
        1. Compare the original clinical text and expanded clinical text.
        2. Check whether the expanded text only expands abbreviations.
        3. Check whether negation, uncertainty, severity, timing, and clinical meaning are preserved.
        4. If the expanded text adds, removes, or changes medical meaning, mark sentence_validity.is_valid as false.

        Mapping-level evaluation for each item:
        1. Check whether the abbreviation appears in the original clinical text.
        2. Check whether the expansion appears in or is clearly reflected by the expanded clinical text.
        3. Check whether the expansion is a plausible medical meaning of the abbreviation in this context.
        4. Check whether SNOMED candidates generally support the expanded term.
        5. If the abbreviation is ambiguous in this context, lower confidence and add an issue.
        6. If SNOMED candidates are weak, unrelated, or missing, set snomed_supported to false and add an issue.

        Issue labels:
        - "abbreviation_not_found"
        - "expansion_not_in_expanded_text"
        - "added_information"
        - "removed_information"
        - "changed_meaning"
        - "negation_changed"
        - "unsupported_by_snomed"
        - "ambiguous_abbreviation"
        - "not_medical_abbreviation"
        - "not_only_abbreviation_expansion"

        Return raw JSON only.
        Do not use markdown.
        Do not include explanations outside the JSON.

        Return JSON in exactly this structure:
        {{
        "sentence_validity": {{
            "is_valid": true,
            "confidence": 0.0,
            "reason": "brief explanation",
            "issues": []
        }},
        "mapping_validations": [
            {{
            "abbreviation": "SOB",
            "expansion": "shortness of breath",
            "context_supported": true,
            "snomed_supported": true,
            "is_valid": true,
            "confidence": 0.0,
            "reason": "brief explanation",
            "issues": []
            }}
        ]
        }}
        """
        response = self.llm.invoke(prompt)
        content = response.content.strip()
        #去掉多余的字符串(防御性编程)
        content = content.replace("```json", "").replace("```", "").strip()
        try:
            #json字符串->python字典
            parsed = json.loads(content)

            sentence_validity = parsed.get("sentence_validity",{})
            mapping_validations = parsed.get("mapping_validations",[])
            #overall_valid = 整句有效 and 有缩写结果 and 所有缩写都有效
            overall_valid=(
                sentence_validity.get("is_valid") is True
                and len(mapping_validations) > 0
                and all(
                    item.get("is_valid") is True
                    for item in mapping_validations
                )
            )
            return{
                "sentence_validity":sentence_validity,
                "mapping_validations":mapping_validations,
                "overall_valid":overall_valid
            }
        except json.JSONDecodeError:
            return {
                "sentence_validity": {
                "is_valid": False,
                "confidence": 0.0,
                "reason": "Verifier did not return valid JSON.",
                "issues": ["invalid_json"]
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