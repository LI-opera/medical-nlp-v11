from langchain_deepseek import ChatDeepSeek
from services.medical_standardizer import MedicalStandardizer
from services.abbr_verifier import ABBVerifier
from services.medical_retriever import MedicalRetriever
from services.abbr_reflection_service import ABBRReflectionService
from services.abbr_candidate_retriever import ABBRCandidateRetriever
from services.abbr_candidate_coverage_evaluator import ABBRCandidateCoverageEvaluator
from services.abbr_candidate_fallback_retriever import ABBRCandidateFallbackRetriever
from services.mapping_support_verifier import MappingSupportVerifier
from data.abbr_candidates import ABBR_CANDIDATES
import json
import re
#加载环境变量
import os
from dotenv import load_dotenv
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ENV_PATH = os.path.join(BACKEND_DIR, ".env")
#加了 override=True 就会强制覆盖旧值，用 .env 里的内容替换 Python 进程里已有的环境变量。
load_dotenv(ENV_PATH,override=True)
#load_dotenv()
#目标
"""ABBRService
    ↓
LLM abbreviation expansion
"""

class ABBRService:
    """医学缩写扩展加医疗术语标准化服务。
        作用:将病例中医学缩写替换为完整术语。
    """
    def __init__(self):
        #拿到DEEPSEEK_API_KEY
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set. Please check backend/.env")
        #初始化创建一个字典里面  缩写：完整字段名称
        self.abbr_dict = {
            "SOB":"shortness of breath",
            "HTN":"hypertension",
            "DM":"diabetes mellitus",
            "CP":"chest pain",
            "CAD":"coronary artery disease",
            "CHF":"congestive heart failure"
        }
        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key = api_key.strip(),
            temperature = 0,
            max_retries = 2
        )
        
        # 这些对象内部可能会加载模型，所以放到 __init__ 里复用
        self.standardizer = MedicalStandardizer()
        self.retriever = MedicalRetriever()
        self.verifier = ABBVerifier()
        self.reflector = ABBRReflectionService()
        self.candidate_retriever = ABBRCandidateRetriever()
        self.fallback_retriever = ABBRCandidateFallbackRetriever()
        self.coverage_evaluator = ABBRCandidateCoverageEvaluator()
        # V10 Experimental Module，当前 V9 Stable 主链路禁用
        self.mapping_support_verifier = MappingSupportVerifier()
    #使用llm将text文本中的简写词给重写
    #返回：1.expanded_text:扩展后的完整文本。2.mappings:每个缩写对应的扩展结果。
    def simple_llm_expansion(self,text:str):
        #使用llm扩展医学缩写
        #1.先从候选库召回abbreviation candidates
        #2.再让llm基于上下文从后选中选择
        abbreviation_candidates = self._get_abbreviation_candidates(text)

        prompt = f"""
        You are a medical abbreviation expansion assistant.

        Task:
        Expand medical abbreviations in the clinical text.

        Important:
        You must choose expansions from the provided abbreviation candidates when candidates are available.

        Clinical text:
        {text}

        Abbreviation candidates after coverage filtering::
        {json.dumps(abbreviation_candidates, ensure_ascii=False, indent=2)}

        Rules:
        1. Only expand medical abbreviations.
        2. Keep the original sentence meaning unchanged.
        3. Do not add diagnosis, explanation, or extra information.
        4. Use filtered_candidates as the primary candidate set.
        5. If filtered_candidates is empty because coverage.coverage_ok is false, do not force an expansion.
        6. If filtered_candidates is empty but coverage.coverage_ok is true, use original candidates with low confidence.
        7. Preserve negation, uncertainty, severity, timing, and clinical meaning.
        8. Return only valid JSON.
        9. Do not use markdown.
        
        Return JSON format:
        {{
        "expanded_text": "expanded clinical text here",
        "mappings": [
            {{
            "abbreviation": "SOB",
            "expansion": "shortness of breath",
            "source": "candidate"
            }},
            {{
            "abbreviation": "XYZ",
            "expansion": null,
            "source": "coverage_failed"
            }}
        ]
        }}
        """
        response = self.llm.invoke(prompt)
        content = response.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {
                "original_text":text,
                "expanded_text":content,
                "mappings":[],
                "abbreviation_candidates": abbreviation_candidates,
                "parse_error":True
            }
        #返回替换前和替换后的句子
        return {
            "original_text": text,
            "expanded_text": parsed.get("expanded_text", text),
            "mappings": parsed.get("mappings", []),
            "abbreviation_candidates": abbreviation_candidates,
            "parse_error": False
        }

    def expand_abbreviations(self,text:str):
        #创建一个text副本，用来之后展示哪些源文本被替换做参照
        expanded_text = text
        #创建一个列表，记录替换历史
        replacements = []

        #将字典的键值对取出，判断文本中是否有需要替换的键
        for abbr,full_term in self.abbr_dict.items():
            #如果缩写在当前文本中
            if abbr in expanded_text:
                #则将文本中的缩写替换为full_term。然后再赋值回expanded_text
                expanded_text = expanded_text.replace(abbr,full_term)
                #如果发生替换，就记录下来
                replacements.append({
                    "abbreviation":abbr,
                    "full_term":full_term
                })
        #返回就文本新文本的对照，以及替换记录
        return{
            "original_text":text,
            "expanded_text":expanded_text,
            "replacements":replacements
        }
    
    def expand_and_standardize(self,text:str):
        """llm缩写扩展 + 医学术语标准化
            同时返回：
            1. 整句扩展后的标准化结果
            2. 每个缩写 expansion 对应的 SNOMED 候选        
        """
        #使用simple_llm_expansion改写text
        expansion_result = self.simple_llm_expansion(text)
        #提取重写的text和重写时改动的词汇
        expanded_text = expansion_result["expanded_text"]
        mappings = expansion_result.get("mappings",[])
        
        #提取新生成的text其中的医学实体
        standardization_result = self.standardizer.standardize(expanded_text)

        
        mapping_standardizations = []
        for mapping in mappings:
            expansion = mapping.get("expansion")

            docs = self.retriever.retrieve(
                query=expansion,
                top_k=10,
                domain_filter=None,
                score_threshold=0.6
            )
            candidates = []
            for doc in docs[:3]:
                metadata = doc["metadata"]

                candidates.append({
                    "concept_id":metadata["concept_id"],
                    "concept_name":metadata["concept_name"],
                    "domain_id":metadata["domain_id"],
                    "concept_code":metadata["concept_code"],
                    "score":metadata["score"],
                    "rerank_score":metadata.get("rerank_score")
                })
            mapping_standardizations.append({
                "abbreviation":mapping["abbreviation"],
                "expansion":expansion,
                "candidates":candidates
            })
        
        return {
            "original_text":text,
            "expanded_text":expanded_text,
            "mappings":mappings,
            "standardization":standardization_result,
            "mapping_standardizations":mapping_standardizations
        }
    
    def expand_standardize_and_verify(self,text:str):
        """
        LLM缩写扩写 + NER/RAG标准化+逐项扩写词校验
        """
        pipeline_result = self.expand_and_standardize(text)

        
        verification = self.verifier.verify_mappings(
            original_text=pipeline_result["original_text"],
            expanded_text=pipeline_result["expanded_text"],
            mapping_standardizations=pipeline_result["mapping_standardizations"]
        )
        return{
            **pipeline_result,
            "verification":verification
        }
    
    def _rebuild_expanded_text(self,original_text:str,mappings:list[dict]) -> str:
        #根据通过 support verification的mappings,重新构建expanded_text
        #目的：如果某个mapping被MappingSupportVerifier拒绝，那么对应缩写应该保留原样，而不是继续出现在expanded_text里
        rebuilt_text = original_text
        for mapping in mappings:
            abbr = mapping.get("abbreviation")
            expansion = mapping.get("expansion")

            if not abbr or not expansion:
                continue
            rebuilt_text = rebuilt_text.replace(abbr,expansion)

        return rebuilt_text

    def _build_expanded_text_deterministic(self, text: str, chosen: list[dict]) -> str:
        """确定性扩写:对每个 {abbreviation -> expansion} 按 token 边界替换。
        - \b...\b 保证不误伤子串(CP 不命中 CPR)
        - 从后往前替,避免多次替换的 offset 错位
        - 只替换 chosen 里有 expansion 的项;否定/其它词原样保留
        """
        if not chosen:
            return text

        spans = []
        for item in chosen:
            abbr = item.get("abbreviation")
            expansion = item.get("expansion")
            if not abbr or not expansion:
                continue
            pattern = re.compile(rf"\b{re.escape(abbr)}\b")
            for match in pattern.finditer(text):
                spans.append((match.start(), match.end(), expansion))

        spans.sort(key=lambda span: span[0], reverse=True)
        result = text
        for start, end, expansion in spans:
            result = result[:start] + expansion + result[end:]
        return result

    def _filter_mappings_by_context_support(
        self, original_text: str, mappings: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """
        使用 MappingSupportVerifier 过滤上下文不支持的 abbreviation -> expansion。

        V10.1 策略：
        1. 单候选缩写：直接通过
        2. 多候选缩写：调用 MappingSupportVerifier
        3. 缺失 abbreviation / expansion：拒绝
        """
        supported_mappings = []
        support_results = []

        for mapping in mappings:
            abbr = mapping.get("abbreviation")
            expansion = mapping.get("expansion")

            if not abbr or not expansion:
                support_results.append({
                    "abbreviation": abbr,
                    "expansion": expansion,
                    "supported": False,
                    "confidence": 0.0,
                    "reason": "Missing abbreviation or expansion.",
                    "gate": "missing_field"
                })
                continue

            # 先查看候选数量
            candidates = self.candidate_retriever.retrieve(abbr)
            candidate_count = len(candidates)

            # V10.1：单候选缩写直接通过
            if candidate_count <= 1:
                supported_mappings.append(mapping)
                support_results.append({
                    "abbreviation": abbr,
                    "expansion": expansion,
                    "supported": True,
                    "confidence": 1.0,
                    "reason": "Single-candidate abbreviation; mapping support verification skipped.",
                    "gate": "single_candidate_pass"
                })
                continue

            # 多候选缩写才调用 MappingSupportVerifier
            support_result = self.mapping_support_verifier.verify(
                text=original_text,
                abbreviation=abbr,
                expansion=expansion
            )

            support_item = {
                "abbreviation": abbr,
                "expansion": expansion,
                "supported": support_result.supported,
                "confidence": support_result.confidence,
                "reason": support_result.reason,
                "gate": "mapping_support_verifier"
            }

            support_results.append(support_item)

            if support_result.supported:
                supported_mappings.append(mapping)

        return supported_mappings, support_results

    #max_retries=2意思是最多允许 Reflection 修正 2 次。加第一次 正常尝试。所以总共最多三次
    def expand_verify_with_retry(self,text:str,max_retries:int=2):
        """
        缩写扩展 + 标准化 + 校验 + Reflection 重试。

        流程：
        1. LLM / Candidate Pipeline 扩写缩写
        2. 如果没有任何有效 expansion，直接失败返回，避免 coverage_failed 空转
        3. 对扩写文本做 NER + SNOMED 标准化
        4. 对 abbreviation -> expansion 做 SNOMED 检索
        5. Verifier 校验
        6. 如果通过，返回成功
        7. 如果不通过，Reflection 修正后重试
        """
        attempts = []
        
        candidate_infos = self._get_abbreviation_candidates(text)

        chosen = []
        for info in candidate_infos:
            best = info.get("best_expansion")
            if not best:
                continue
            chosen.append({
                "abbreviation": info["abbreviation"],
                "expansion": best,
                "label": info.get("chosen_label"),
                "source": info.get("candidate_source"),
            })

        current_expanded_text = self._build_expanded_text_deterministic(text, chosen)
        current_mappings = [
            {
                "abbreviation": item["abbreviation"],
                "expansion": item["expansion"],
                "label": item["label"],
                "source": item["source"],
            }
            for item in chosen
        ]
        current_abbreviation_candidates = candidate_infos

        mapping_support_results = []
        # V9 Stable：不做 MappingSupportVerifier 过滤
        # 保留 simple_llm_expansion 原始输出
        # current_mappings 不变
        # current_expanded_text 不重建
        # current_mappings, mapping_support_results = self._filter_mappings_by_context_support(
        #     original_text=text,
        #     mappings=current_mappings
        # )

        # current_expanded_text = self._rebuild_expanded_text(
        #     original_text=text,
        #     mappings=current_mappings
        # )

        for attempt_index in range(max_retries+1):
            #只保留真正有expansion的mapping
            #例如 {"abbreviation": "XYZ", "expansion": None} 不应该继续 SNOMED 检索
            valid_mappings = current_mappings

            #如果一个有效扩写都没有，说明coverage全失败
            #这种情况Reflection也没有候选可修，不要空转重试
            if not current_mappings:
                attempt_result = {
                    "attempt": attempt_index + 1,
                    "expanded_text": current_expanded_text,
                    "abbreviation_candidates": current_abbreviation_candidates,
                    "mappings": current_mappings,
                    "standardization": None,
                    "mapping_standardizations": [],
                    "verification": {
                        "sentence_validity": {
                            "is_valid": True,
                            "confidence": 1.0,
                            "reason": "No valid abbreviation expansion was produced; the text was left unchanged.",
                            "issues": []
                        },
                        "mapping_validations": [],
                        "overall_valid": False
                    },
                    "stop_reason": "coverage_failed_no_valid_expansion",
                    "mapping_support_results": mapping_support_results
                }

                attempts.append(attempt_result)

                return {
                "original_text": text,
                "final_expanded_text": current_expanded_text,
                "success": False,
                "attempts": attempts,
                "final_result": attempt_result,
                "reason": "No valid abbreviation expansion found. Candidate coverage failed."
            }


            #对当前扩写文本做标准化
            standardization_result = self.standardizer.standardize(current_expanded_text)

            mapping_standardizations = []

            for mapping in valid_mappings:
                expansion = mapping.get("expansion")

                docs = self.retriever.retrieve(
                    query=expansion,
                    top_k=10,
                    domain_filter=None,
                    score_threshold=0.6
                )

                candidates = []

                for doc in docs[:3]:
                    metadata = doc["metadata"]

                    candidates.append({
                        "concept_id":metadata["concept_id"],
                        "concept_name":metadata["concept_name"],
                        "domain_id":metadata["domain_id"],
                        "concept_code":metadata["concept_code"],
                        "score":metadata["score"],
                        "rerank_score":metadata.get("rerank_score")
                    })
                mapping_standardizations.append({
                    "abbreviation":mapping["abbreviation"],
                    "expansion":expansion,
                    "candidates":candidates
                })

            #Verfier校验
            #创建检验器
            verification = self.verifier.verify_mappings(
                original_text=text,
                expanded_text=current_expanded_text,
                mapping_standardizations=mapping_standardizations
            )

            #保存本次尝试结果
            attempt_result = {
                "attempt": attempt_index + 1,
                "expanded_text": current_expanded_text,

                # 缩写候选召回 + coverage + filtered_candidates
                "abbreviation_candidates": current_abbreviation_candidates,

                # LLM 最终选择出来的 abbreviation -> expansion
                "mappings": current_mappings,

                # 扩写后文本的 NER + SNOMED 标准化结果
                "standardization": standardization_result,

                # 每个 abbreviation -> expansion 的 SNOMED 检索结果
                "mapping_standardizations": mapping_standardizations,

                # 双层校验结果
                "verification": verification,
                "mapping_support_results": mapping_support_results
            }
            #把这次尝试放进历史记录
            attempts.append(attempt_result)

            #如果检验通过了直接返回
            if verification.get("overall_valid") is True:
                return {
                    "original_text":text,
                    "final_expanded_text":current_expanded_text,
                    "success":True,
                    "attempts":attempts,
                    "final_result":attempt_result
                }
            #如果次数用完就停止
            if attempt_index >= max_retries:
                return {
                "original_text": text,
                "final_expanded_text": current_expanded_text,
                "success": False,
                "attempts": attempts,
                "final_result": attempt_result
            }

            #Reflection修正
            #创建反思修正服务，作用：根据verifier给出的错误，尝试修正expanded_text
            #给修正器提供参数，让其重新生成扩写文本
            reflection_result = self.reflector.reflect(
                original_text=text,
                previous_expanded_text=current_expanded_text,
                verification=verification,
                abbreviation_candidates=current_abbreviation_candidates
            )
            #更新当前的扩写文本
            current_expanded_text = reflection_result["revised_expanded_text"]

            revised_mappings = reflection_result.get("revised_mappings",[])

            if revised_mappings:
                current_mappings = revised_mappings
        return {
            "original_text": text,
            "final_expanded_text": current_expanded_text,
            "success": False,
            "attempts": attempts,
            "final_result": attempts[-1] if attempts else None
        }

    #召回候选+覆盖度评估
    def _get_abbreviation_candidates(self,text:str):
        """
        从文本中识别缩写，并召回候选扩展。

        流程：
        1. 先判断 token 是否像缩写
        2. 已知缩写走 primary retriever
        3. primary 没有结果时走 fallback retriever
        4. 对候选做 coverage evaluation
        5. 根据 plausible_candidates 得到 filtered_candidates
        """

        #取出当前候选库中已有的缩写，比如{"SOB", "DM", "HTN", "CP"}
        known_abbrs = set(ABBR_CANDIDATES.keys())

        found = []
        #将text里各个单词格式化，好挨个遍历
        words = text.replace(","," ").replace("."," ").split()

        for word in words:
            #保留原始大小写，只去掉标点
            raw_token = word.strip(".,;:()[]{}")
            #新增关键gate.如果token不想缩写，而是常用单词直接跳过
            if not self._should_consider_abbreviation(raw_token,known_abbrs):
                continue
            ## 只有通过 gate 后，才统一转大写用于查库
            abbr = raw_token.strip().upper()

            #第一层：主候选库召回
            candidates = self.candidate_retriever.retrieve(abbr)
            candidate_source = "primary"

            #第二层：如果主候选库没有结果，走fallback retriever
            if not candidates:
                fallback_result = self.fallback_retriever.retrieve(
                    abbreviation=abbr,
                    context_text=text
                )
                candidates = fallback_result.get("candidates",[])
                candidate_source = "fallback"
            
            #如果primary和fallback都没有候选
            if not candidates:
                found.append({
                    "abbreviation":abbr,
                    "candidates": [],
                    "filtered_candidates": [],
                    "coverage": {
                        "abbreviation": abbr,
                        "coverage_ok": False,
                        "confidence": 0.0,
                        "plausible_candidates": [],
                        "reason": "No candidates found from primary or fallback retriever.",
                        "issues": ["no_candidates"]
                    },
                    "candidate_source": "none",
                    "best_expansion": None,
                    "chosen_label": None,
                    "chosen_domain": None
                })
                continue
            
            #第三层：对候选做coverage evaluation
            coverage = self.coverage_evaluator.evaluate(
                original_text=text,
                abbreviation=abbr,
                candidates=candidates
            )
            #将覆盖评估中的合适的候选词名单拿出来
            plausible_expansions = coverage.get("plausible_candidates",[])

            filtered_candidates=[
                candidate for candidate in candidates if candidate["expansion"] in plausible_expansions
            ]

            best = coverage.get("best_expansion")
              
            #将缩写，候选表，候选覆盖情况返回
            found.append({
                "abbreviation":abbr,
                "candidates":candidates,
                "filtered_candidates":filtered_candidates,
                "coverage":coverage,
                "candidate_source":candidate_source,
                "best_expansion":best,
                "chosen_label":None,
                "chosen_domain":None
            })
        return found

    def _should_consider_abbreviation(self,raw_token:str,known_abbrs:set[str])->bool:
        #判断一个token是否值得进入缩写候选召回流程。
        #设计原则：
        #1.已知缩写：大小写都允许，例如 SOB/sob/DM/dm
        #2.位置缩写，只有原文就是大写时才允许进入fallback，例如AKI/XYZ
        #3.未知小写词：暂时跳过，不是不可能，而是证据不足
        token = raw_token.strip(".,;:()[]{}")

        #空token直接跳过
        if not token:
            return False
        
        #转写为大写
        upper_token = token.upper()

        #检测是否为纯字母
        if not upper_token.isalpha():
            return False
        #已知缩写直接放行
        if upper_token in known_abbrs:
            return True
        
        #单字符未知token跳过
        if len(upper_token)<2:
            return False
        
        #未知但原文大写，允许fallback
        if token == upper_token and len(upper_token) <=8:
            return True
        
        #其他情况跳过
        return False

    













"""
original_text
    原始输入

expanded_text
    LLM 扩写后的整句话

mappings
    LLM 明确告诉你：哪个缩写被扩成了什么

standardization
    对 expanded_text 整句话做 NER + SNOMED 检索

mapping_standardizations
    对每个 expansion 单独做 SNOMED 检索

verification
    LLM 根据 original_text、expanded_text、mapping_standardizations 逐项判断扩写是否可信
"""
