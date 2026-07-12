import json
import os
import time
from dotenv import load_dotenv
from utils.llm_config import DEEPSEEK_CONFIG, LLMConfig
from utils.llm_factory import create_llm
from utils.structured_logger import exc_meta, log_dependency

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ENV_PATH = os.path.join(BACKEND_DIR,".env")

load_dotenv(ENV_PATH, override=False)

class ABBVerifier:
    """
    医学缩写扩展校验器：
    作用：判断LLM扩写后的文本是否保持愿意，并且是否能被后续SNOMED标准化结果支持
    """
    def __init__(self, config: LLMConfig = DEEPSEEK_CONFIG):
        self.llm = create_llm(config)
        self.config = config

    def _invoke_llm(self, prompt: str, purpose: str, **fields):
        start = time.perf_counter()
        log_dependency(
            "dependency.llm.call_start",
            component="ABBVerifier",
            provider=str(self.config.provider),
            model_name=self.config.model_name,
            purpose=purpose,
            ok=True,
            **fields,
        )
        try:
            response = self.llm.invoke(prompt)
        except Exception as exc:
            log_dependency(
                "dependency.llm.call_error",
                component="ABBVerifier",
                provider=str(self.config.provider),
                model_name=self.config.model_name,
                purpose=purpose,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                ok=False,
                level="ERROR",
                **fields,
                **exc_meta(exc),
            )
            raise
        log_dependency(
            "dependency.llm.call_ok",
            component="ABBVerifier",
            provider=str(self.config.provider),
            model_name=self.config.model_name,
            purpose=purpose,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            output_len=len(getattr(response, "content", "") or ""),
            ok=True,
            **fields,
        )
        return response
    
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
        response = self._invoke_llm(prompt, "sentence_verification")
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

        Your job is to pick the BEST FAITHFUL standardization of the expansion among
        the candidates, and to abstain ONLY when none is faithful.

        A candidate is FAITHFUL when its concept_name denotes the SAME clinical entity
        as the expansion. This includes:
        - an exact clinical synonym of the expansion (most preferred); and
        - the SAME disease/finding named more GENERALLY, i.e. a faithful PARENT term,
          when no exact synonym is present. For example, for "coronary artery disease"
          the candidates "Disorder of coronary artery" and "Coronary arteriosclerosis"
          are faithful; for "hypertension" the candidate "Hypertensive disorder" is
          faithful.

        A candidate is NOT faithful (do not choose it; if only such candidates exist,
        abstain):
        - it ADDS a qualifier the expansion does not state - a specific subtype, cause,
          stage, acuity, laterality or site (e.g. "... due to diabetes",
          "type 1 stage 2", "acute ...", "of inferior wall") - UNLESS the expansion
          itself carries that qualifier; or
        - it is a related-but-different concept: a rating scale, measurement, procedure,
          device, service, monitoring / education / administration, risk level, or
          family history. For example, "chest pain" and "Chest pain rating" are not the
          same clinical thing.

        How to choose:
        - chosen_index = the zero-based index of the BEST faithful candidate. Among
          faithful candidates, prefer the MOST SPECIFIC one that does NOT add information
          absent from the expansion (prefer the disease itself over a broad parent, and
          over the disease's subtypes or related services).
        - Do NOT abstain just because no candidate is a word-for-word match: a faithful
          synonym or a faithful parent still counts as faithful.
        - chosen_index = null ONLY when no candidate denotes the same clinical entity.
        - standardization_faithful must be true only when chosen_index points to a
          faithful candidate.
        - Judge concept_name against the expansion's clinical meaning. Do not trust the
          retrieval score by itself.
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

        response = self._invoke_llm(
            prompt,
            "mapping_verification",
            mapping_count=len(mapping_standardizations),
        )
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

    def propose_requeries(self, expansion: str, current_concept, seen_concepts):
        """标准化反思:为 expansion 提出最多 2 个【同义/规范检索词】。
        以图检回比 current_concept 更标准的 SNOMED 概念。
        只产检索词,绝不产/选择概念。
        """
        prompt = f"""
        You are refining a SNOMED standardization by REFORMULATING the search query.

        Clinical term (expansion): {expansion}
        Current best SNOMED concept: {current_concept if current_concept else "none yet"}
        Already-retrieved concepts (avoid repeating): {json.dumps(list(seen_concepts), ensure_ascii=False)}

        Propose up to 2 alternative SEARCH phrasings for "{expansion}" - exact clinical
        synonyms or the single standard medical term - likely to retrieve a MORE STANDARD
        / more canonical SNOMED concept than the current one.
        - Output SEARCH WORDS only. Never invent or output a SNOMED concept.
        - Each phrasing must mean EXACTLY the same clinical thing as the expansion; do not
          add a subtype, cause, stage, acuity, site, or mechanism.
        - Do not propose a mechanism term that the expansion does not state. For example,
          for "coronary artery disease", do NOT propose "coronary arteriosclerosis" or
          "atherosclerosis"; keep the search faithful to the stated expansion.
        - If you cannot think of a faithful alternative, return an empty list.
        - Return raw valid JSON only, no markdown: {{"requeries": ["phrase one", "phrase two"]}}
        """
        try:
            response = self._invoke_llm(
                prompt,
                "standardization_requery",
                expansion=expansion,
                seen_count=len(seen_concepts or []),
            )
            content = response.content.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(content)
            out = []
            expansion_lower = expansion.strip().lower()
            mechanism_terms = ("arteriosclerosis", "atherosclerosis")
            for q in data.get("requeries", []):
                if not isinstance(q, str) or not q.strip():
                    continue
                query = q.strip()
                query_lower = query.lower()
                if query_lower == expansion_lower:
                    continue
                if any(term in query_lower and term not in expansion_lower for term in mechanism_terms):
                    continue
                out.append(query)
            return out[:2]
        except Exception:
            return []

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
