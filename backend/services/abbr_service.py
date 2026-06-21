from langchain_deepseek import ChatDeepSeek
from services.medical_standardizer import MedicalStandardizer
from services.abbr_verifier import ABBVerifier
from services.medical_retriever import MedicalRetriever
from services.abbr_candidate_retriever import ABBRCandidateRetriever
from services.abbr_candidate_coverage_evaluator import ABBRCandidateCoverageEvaluator
from services.abbr_candidate_fallback_retriever import ABBRCandidateFallbackRetriever
from data.abbr_candidates import ABBR_CANDIDATES
import re
#加载环境变量
import os
from dotenv import load_dotenv

# NER 实体标签 → SNOMED domain_id(库里实际取值:Condition/Observation/Measurement/
# Procedure/Drug/Spec Anatomic Site/Device 等)。映射不完美没关系——domain_boost 是软加分。
NER_LABEL_TO_DOMAIN = {
    "DISEASE_DISORDER": "Condition",
    "SIGN_SYMPTOM": "Condition",
    "BIOLOGICAL_STRUCTURE": "Spec Anatomic Site",
    "MEDICATION": "Drug",
    "DIAGNOSTIC_PROCEDURE": "Procedure",
    "THERAPEUTIC_PROCEDURE": "Procedure",
    "LAB_VALUE": "Measurement",
    "DETAILED_DESCRIPTION": "Observation",
}

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
        self.ner_service = self.standardizer.ner_service
        self.retriever = MedicalRetriever()
        self.verifier = ABBVerifier()
        self.candidate_retriever = ABBRCandidateRetriever()
        self.fallback_retriever = ABBRCandidateFallbackRetriever()
        self.coverage_evaluator = ABBRCandidateCoverageEvaluator()
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

        # —— 建 per-mapping 状态机条目 ——
        states = []
        for info in candidate_infos:
            best = info.get("best_expansion")
            if not best:
                continue
            # 候选池(确定性 reflect 的换候选空间);保证 best 排最前
            pool = [c.get("expansion") for c in info.get("candidates", []) if c.get("expansion")]
            if best in pool:
                pool = [best] + [e for e in pool if e != best]
            else:
                pool = [best] + pool
            states.append({
                "abbreviation": info["abbreviation"],
                "expansion": best,
                "label": info.get("chosen_label"),
                "domain": info.get("chosen_domain"),
                "source": info.get("candidate_source"),
                "status": "PENDING",
                "pool": pool,
                "tried": {best},
                "std_cache": None,
                "changed": True,
            })

        current_abbreviation_candidates = candidate_infos
        mapping_support_results = []
        standardization_result = None

        def _visible(state_list):
            # 进入句子/检索的 mapping:未弃权的(LOCKED_OK + PENDING)
            return [s for s in state_list if s["status"] != "LOCKED_ABSTAIN"]

        current_expanded_text = self._build_expanded_text_deterministic(text, _visible(states))

        # —— 早停:召回阶段没选出任何扩写 ——
        if not states:
            attempt_result = {
                "attempt": 1,
                "expanded_text": current_expanded_text,
                "abbreviation_candidates": current_abbreviation_candidates,
                "mappings": [],
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

        # —— 重试循环:per-mapping 失败隔离 + 增量重算 ——
        for attempt_index in range(max_retries + 1):
            pending = [s for s in states if s["status"] == "PENDING"]
            if not pending:
                break

            # 增量检索:只对本轮 expansion 变过的 PENDING 重检索
            for s in pending:
                if s["changed"]:
                    docs = self.retriever.retrieve(
                        query=s["expansion"],
                        top_k=10,
                        domain_filter=None,
                        domain_boost=s.get("domain"),
                        score_threshold=0.6
                    )
                    cand = []
                    for doc in docs[:3]:
                        md = doc["metadata"]
                        cand.append({
                            "concept_id": md["concept_id"],
                            "concept_name": md["concept_name"],
                            "domain_id": md["domain_id"],
                            "concept_code": md["concept_code"],
                            "score": md["score"],
                            "rerank_score": md.get("rerank_score"),
                        })
                    s["std_cache"] = cand
                    s["changed"] = False

            # 只对 PENDING 做 verify(LOCKED_OK 冻结不复验)
            mapping_standardizations = [
                {
                    "abbreviation": s["abbreviation"],
                    "expansion": s["expansion"],
                    "candidates": s["std_cache"],
                }
                for s in pending
            ]
            verification = self.verifier.verify_mappings(
                original_text=text,
                expanded_text=current_expanded_text,
                mapping_standardizations=mapping_standardizations,
            )
            validations = verification.get("mapping_validations", [])

            def _find_validation(abbr):
                for v in validations:
                    if v.get("abbreviation") == abbr:
                        return v
                return None

            # 逐个 PENDING 判定:通过→LOCKED_OK;不过→换未试候选 or 弃权
            for s in pending:
                v = _find_validation(s["abbreviation"])
                passed = bool(v and v.get("is_valid") is True)
                if passed:
                    s["status"] = "LOCKED_OK"
                else:
                    untried = [e for e in s["pool"] if e not in s["tried"]]
                    if untried:
                        # 选择型 reflect:取池里下一个未试候选(确定性,不调 LLM)
                        s["expansion"] = untried[0]
                        s["tried"].add(untried[0])
                        s["changed"] = True
                    else:
                        s["status"] = "LOCKED_ABSTAIN"

            # 用未弃权的 mapping 重新确定性拼句
            current_expanded_text = self._build_expanded_text_deterministic(text, _visible(states))

            # 本轮留痕
            attempts.append({
                "attempt": attempt_index + 1,
                "expanded_text": current_expanded_text,
                "abbreviation_candidates": current_abbreviation_candidates,
                "mappings": [
                    {
                        "abbreviation": s["abbreviation"],
                        "expansion": s["expansion"],
                        "label": s["label"],
                        "source": s["source"],
                        "status": s["status"],
                    }
                    for s in states
                ],
                "standardization": standardization_result,
                "mapping_standardizations": mapping_standardizations,
                "verification": verification,
                "mapping_support_results": mapping_support_results,
            })

        # —— 循环结束:到达兜底次数仍 PENDING 的 → 安全弃权 ——
        for s in states:
            if s["status"] == "PENDING":
                s["status"] = "LOCKED_ABSTAIN"

        # —— 终态出口 ——
        current_expanded_text = self._build_expanded_text_deterministic(text, _visible(states))
        locked_ok = [s for s in states if s["status"] == "LOCKED_OK"]
        final_mappings = [
            {
                "abbreviation": s["abbreviation"],
                "expansion": s["expansion"],
                "label": s["label"],
                "source": s["source"],
            }
            for s in locked_ok
        ]
        success = len(states) > 0 and all(s["status"] == "LOCKED_OK" for s in states)

        final_result = {
            "attempt": len(attempts),
            "expanded_text": current_expanded_text,
            "abbreviation_candidates": current_abbreviation_candidates,
            "mappings": final_mappings,
            "standardization": standardization_result,
            "mapping_standardizations": [
                {
                    "abbreviation": s["abbreviation"],
                    "expansion": s["expansion"],
                    "candidates": s["std_cache"],
                }
                for s in locked_ok
            ],
            "verification": attempts[-1]["verification"] if attempts else None,
            "mapping_support_results": mapping_support_results,
            "mapping_states": [
                {"abbreviation": s["abbreviation"], "expansion": s["expansion"], "status": s["status"]}
                for s in states
            ],
        }

        return {
            "original_text": text,
            "final_expanded_text": current_expanded_text,
            "success": success,
            "attempts": attempts,
            "final_result": final_result,
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

            if candidate_source == "fallback":
                for candidate in candidates:
                    _, label, _ = self.ner_service.is_medical(candidate.get("expansion"))
                    candidate["domain"] = NER_LABEL_TO_DOMAIN.get(label)
            
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

            # 批次3(攻弃权):对 fallback(非词典)缩写收紧
            # 词典缩写(primary)是人工策展可信源 → 照常;
            # fallback 缩写是 LLM 现造的,上下文证据不足就弃权,不替它背书
            # (治 QRS→"QRS complex"、NOP→"no operation/Nocturnal Oxygen Protocol"、MNO 等过度扩写)
            if candidate_source == "fallback":
                conf = coverage.get("confidence") or 0.0
                if (not coverage.get("coverage_ok")) or conf < 0.8:
                    best = None

            # batch4:取选中候选的 domain
            best_domain = None
            if best:
                for candidate in candidates:
                    if candidate.get("expansion") == best:
                        best_domain = candidate.get("domain")
                        break
              
            #将缩写，候选表，候选覆盖情况返回
            found.append({
                "abbreviation":abbr,
                "candidates":candidates,
                "filtered_candidates":filtered_candidates,
                "coverage":coverage,
                "candidate_source":candidate_source,
                "best_expansion":best,
                "chosen_label":None,
                "chosen_domain":best_domain
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
