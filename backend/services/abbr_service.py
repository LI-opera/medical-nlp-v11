from services.abbr_verifier import ABBVerifier
from services.medical_retriever import MedicalRetriever
from services.medical_ner import MedicalNER
from services.abbr_candidate_retriever import ABBRCandidateRetriever
from services.abbr_candidate_coverage_evaluator import ABBRCandidateCoverageEvaluator
from services.abbr_candidate_fallback_retriever import ABBRCandidateFallbackRetriever
from data.abbr_candidates import ABBR_CANDIDATES, reload_abbr_candidates_if_changed
import re
import time
from utils.structured_logger import log_pipeline, text_meta
#加载环境变量
import os
from dotenv import load_dotenv

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ENV_PATH = os.path.join(BACKEND_DIR, ".env")
#加了 override=True 就会强制覆盖旧值，用 .env 里的内容替换 Python 进程里已有的环境变量。
load_dotenv(ENV_PATH, override=False)
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
        # 这些对象内部可能会加载模型，所以放到 __init__ 里复用
        self.ner_service = MedicalNER()
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

    @staticmethod
    def _route_source(domain):
        return "rxnorm" if domain == "Drug" else "snomed"

    @staticmethod
    def _build_success_breakdown(records):
        """Business success is scoped to abbreviation records, not all entities."""
        target_records = records
        target_count = len(target_records)
        expanded_count = sum(1 for r in target_records if r.get("expansion"))
        coded_count = sum(1 for r in target_records if r.get("status") == "CODED")
        withheld_count = sum(1 for r in target_records if r.get("status") == "WITHHELD")
        not_expanded_count = sum(1 for r in target_records if r.get("status") == "NOT_EXPANDED")
        abstain_count = sum(1 for r in target_records if r.get("status") == "ABSTAIN")
        pending_count = sum(1 for r in target_records if r.get("status") == "PENDING")

        expansion_success = (
            target_count > 0
            and all(bool(r.get("expansion")) for r in target_records)
        )
        standardization_success = (
            target_count > 0
            and all(r.get("status") == "CODED" for r in target_records)
        )

        return {
            "expansion_success": expansion_success,
            "standardization_success": standardization_success,
            "target_count": target_count,
            "expanded_count": expanded_count,
            "coded_count": coded_count,
            "withheld_count": withheld_count,
            "not_expanded_count": not_expanded_count,
            "abstain_count": abstain_count,
            "pending_count": pending_count,
        }

    @staticmethod
    def _build_not_expanded_failure(abbr, candidates, coverage, candidate_source, retrieval_trace=None):
        retrieval_trace = retrieval_trace or {}
        plausible = coverage.get("plausible_candidates") or []
        issues = coverage.get("issues") or []
        confidence = coverage.get("confidence") or 0.0
        candidate_expansions = [c.get("expansion") for c in candidates or []]

        evidence = {
            "candidate_source": candidate_source,
            "candidate_count": len(candidates or []),
            "candidates_seen": candidate_expansions,
            "plausible_candidates": plausible,
            "coverage_confidence": confidence,
            "coverage_ok": coverage.get("coverage_ok"),
            "coverage_issues": issues,
            "primary_called": retrieval_trace.get("primary_called"),
            "primary_candidate_count": retrieval_trace.get("primary_candidate_count"),
            "fallback_called": retrieval_trace.get("fallback_called"),
            "fallback_candidate_count": retrieval_trace.get("fallback_candidate_count"),
            "fallback_reason": retrieval_trace.get("fallback_reason"),
            "fallback_error_kind": retrieval_trace.get("fallback_error_kind"),
            "fallback_raw_output": retrieval_trace.get("fallback_raw_output"),
            "fallback_error": retrieval_trace.get("fallback_error"),
        }

        if not candidates:
            fallback_failed = bool(
                evidence.get("fallback_error_kind")
                or evidence.get("fallback_raw_output")
                or evidence.get("fallback_error")
            )
            subtype = "FALLBACK_FAILED" if fallback_failed else "FALLBACK_RETURNED_EMPTY"
            reason = (
                "Fallback retriever failed before returning usable candidates."
                if fallback_failed
                else "No expansion candidates were returned by primary or fallback retriever."
            )
            suggestion = (
                "Check fallback API, JSON format, or runtime configuration."
                if fallback_failed
                else "Need more clinical context or abbreviation dictionary/source update."
            )
            return {
                "type": "NO_CANDIDATES",
                "subtype": subtype,
                "stage": "candidate_retrieval",
                "reason": reason,
                "suggestion": suggestion,
                "evidence": evidence,
            }

        ambiguous = len(plausible) > 1 or (
            len(candidate_expansions) > 1
            and bool(plausible)
            and confidence < 0.8
        )
        if ambiguous:
            return {
                "type": "AMBIGUOUS_LOW_CONTEXT",
                "stage": "candidate_coverage",
                "reason": "Multiple candidate expansions remain plausible, but context is insufficient to choose safely.",
                "suggestion": "Return abstain/not expanded and request more clinical context instead of retrying fallback.",
                "evidence": evidence,
            }

        return {
            "type": "CANDIDATES_REJECTED_BY_COVERAGE",
            "stage": "candidate_coverage",
            "reason": coverage.get("reason") or "Candidates exist, but coverage evaluation did not support a safe expansion.",
            "suggestion": "Review candidate source quality or add stronger context evidence before expanding.",
            "evidence": evidence,
        }

    @staticmethod
    def _std_rank(s):
        """标准化质量秩:2=精确同名,1=忠实非同名,0=弃码。"""
        sc = s.get("std_concept")
        if not sc:
            return 0
        name = (sc.get("concept_name") or "").strip().lower()
        return 2 if name == s["expansion"].strip().lower() else 1

    def _reflect_refine_standardization(self, s, original_text, expanded_text, max_iter=None):
        """batch10 → L3-6d:标准化反思【真迭代】。
        每轮:非精确同名(或弃码)时换同义词重检索 → verify 重选(保守门);
        只有本轮秩严格变高才再来一轮,否则停。带新证据,非同源复判。
        max_iter 默认读 env REFLECT_MAX_ITER(默认 2),便于 ablation。
        """
        if max_iter is None:
            max_iter = int(os.getenv("REFLECT_MAX_ITER", "2"))
        tried = {s["expansion"].strip().lower()}
        for iter_index in range(max_iter):
            rank_before = self._std_rank(s)
            if rank_before == 2:
                return  # 已精确同名,不可能更好
            chosen = s.get("std_concept")
            chosen_name = chosen.get("concept_name") if chosen else None
            seen = [c["concept_name"] for c in s["std_cache"]]
            requeries = self.verifier.propose_requeries(s["expansion"], chosen_name, seen) or []
            new_terms = [q for q in requeries if q.strip().lower() not in tried]
            if not new_terms:
                return  # 没有没试过的新方向
            tried.update(q.strip().lower() for q in new_terms)

            pool = {c["concept_id"]: c for c in s["std_cache"]}
            for rq in new_terms:
                docs = self.retriever.retrieve(
                    query=rq,
                    top_k=10,
                    domain_filter=None,
                    domain_boost=s.get("domain"),
                    score_threshold=0.6,
                    source=self._route_source(s.get("domain")),
                )
                for doc in docs:
                    md = doc["metadata"]
                    if md["concept_id"] not in pool:
                        pool[md["concept_id"]] = {
                            "concept_id": md["concept_id"],
                            "concept_name": md["concept_name"],
                            "domain_id": md["domain_id"],
                            "concept_code": md["concept_code"],
                            "score": md["score"],
                            "rerank_score": md.get("rerank_score"),
                        }
            new_cands = sorted(pool.values(), key=lambda c: float(c.get("score") or 0), reverse=True)[:15]
            if len(new_cands) <= len(s["std_cache"]):
                return  # 没带回新候选

            verification = self.verifier.verify_mappings(
                original_text=original_text,
                expanded_text=expanded_text,
                mapping_standardizations=[{
                    "abbreviation": s["abbreviation"],
                    "expansion": s["expansion"],
                    "candidates": new_cands,
                }],
            )
            vs = verification.get("mapping_validations", [])
            v = vs[0] if vs else None
            ci = v.get("chosen_index") if v else None
            faithful = bool(v and v.get("standardization_faithful") is True)
            accepted = False
            if faithful and isinstance(ci, int) and not isinstance(ci, bool) and 0 <= ci < len(new_cands):
                refined = new_cands[ci]
                requery_names = {q.strip().lower() for q in new_terms}
                if refined.get("concept_name", "").strip().lower() in requery_names:
                    refined_rank = 2 if refined.get("concept_name", "").strip().lower() == s["expansion"].strip().lower() else 1
                    if refined_rank <= rank_before:
                        if iter_index == 0:
                            s["std_cache"] = new_cands
                            s["std_concept"] = refined
                        return  # 首轮保留单趟反思;后续横移不采纳,避免多轮扰动
                    s["std_cache"] = new_cands
                    s["std_concept"] = refined
                    accepted = True
            if not accepted:
                return  # 本轮没产出可采纳结果
        return

    def expand_verify_with_retry(self, text: str, max_retries: int = 2):
        # 这是生产主链路的编排入口：先完成候选检索和 coverage 判断，再进行
        # 确定性文本替换；已经接受的扩写词随后进入标准化、验证和反思流程。
        """Expand abbreviations, standardize, and verify with a unified data flow.
        Each abbreviation uses one record from retrieval through final output, with
        explicit lifecycle status (NOT_EXPANDED/PENDING/CODED/WITHHELD/ABSTAIN)
        and failure details. Existing response fields are preserved while strict
        success details are added.
        """
        pipeline_start = time.perf_counter()
        log_pipeline(
            "pipeline.start",
            component="ABBRService",
            max_retries=max_retries,
            ok=True,
            **text_meta(text),
        )
        attempts = []
        candidate_infos = self._get_abbreviation_candidates(text)
        current_abbreviation_candidates = candidate_infos

        # Unified per-abbreviation record: one shape from retrieval to output.
        records = []
        for info in candidate_infos:
            best = info.get("best_expansion")
            rec = {
                "abbreviation": info.get("abbreviation"),
                "source": info.get("candidate_source"),
                "candidates": info.get("candidates") or [],
                "coverage": info.get("coverage") or {},
                "expansion": best if best else None,
                "label": info.get("chosen_label"),
                "domain": info.get("chosen_domain"),
                "std_cache": None,
                "std_concept": None,
                "status": "PENDING" if best else "NOT_EXPANDED",
                "failure": None,
            }
            if rec["status"] == "NOT_EXPANDED":
                cov = rec["coverage"]
                rec["failure"] = info.get("failure") or {
                    "type": "ABBR_NOT_EXPANDED",
                    "stage": "coverage",
                    "reason": "coverage withheld expansion (not confident enough)",
                    "suggestion": "Need more clinical context or candidate source update.",
                    "evidence": {
                        "candidate_source": rec.get("source"),
                        "coverage_confidence": cov.get("confidence"),
                        "coverage_ok": cov.get("coverage_ok"),
                        "coverage_issues": cov.get("issues"),
                        "candidates_seen": [c.get("expansion") for c in rec["candidates"]],
                    },
                }
            records.append(rec)

        def _expanded(recs):
            return [r for r in recs if r["expansion"]]

        def _visible(recs):
            # Visible in text/retrieval: expanded and not abstained.
            return [r for r in recs if r["expansion"] and r["status"] != "ABSTAIN"]

        current_expanded_text = self._build_expanded_text_deterministic(text, _visible(records))

        # Early stop: no abbreviation produced an expansion (coverage_failed).
        if not _expanded(records):
            success_breakdown = self._build_success_breakdown(records)
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
                "mapping_states": [
                    {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                     "source": r["source"], "status": r["status"],
                     "domain": r.get("domain"),
                     "chosen_concept": r.get("std_concept"),
                     "coverage": r["coverage"], "failure": r["failure"]}
                    for r in records
                ],
                "success_breakdown": success_breakdown,
            }
            attempts.append(attempt_result)
            log_pipeline(
                "pipeline.final",
                component="ABBRService",
                duration_ms=round((time.perf_counter() - pipeline_start) * 1000, 2),
                success=False,
                expansion_success=success_breakdown["expansion_success"],
                standardization_success=success_breakdown["standardization_success"],
                target_count=success_breakdown["target_count"],
                expanded_count=success_breakdown["expanded_count"],
                coded_count=success_breakdown["coded_count"],
                withheld_count=success_breakdown["withheld_count"],
                not_expanded_count=success_breakdown["not_expanded_count"],
                stop_reason="coverage_failed_no_valid_expansion",
                ok=True,
            )
            return {
                "original_text": text,
                "final_expanded_text": current_expanded_text,
                "success": False,
                "expansion_success": success_breakdown["expansion_success"],
                "standardization_success": success_breakdown["standardization_success"],
                "success_breakdown": success_breakdown,
                "attempts": attempts,
                "final_result": attempt_result,
                "reason": "No valid abbreviation expansion found. Candidate coverage failed.",
            }

        # Retry loop: per-mapping failure isolation.
        for attempt_index in range(max_retries + 1):
            pending = [r for r in records if r["status"] == "PENDING"]
            if not pending:
                break

            # Retrieve SNOMED candidates for each PENDING record.
            for r in pending:
                docs = self.retriever.retrieve(
                    query=r["expansion"],
                    top_k=10,
                    domain_filter=None,
                    domain_boost=r.get("domain"),
                    score_threshold=0.6,
                    source=self._route_source(r.get("domain")),
                )
                r["std_cache"] = [
                    {
                        "concept_id": d["metadata"]["concept_id"],
                        "concept_name": d["metadata"]["concept_name"],
                        "domain_id": d["metadata"]["domain_id"],
                        "concept_code": d["metadata"]["concept_code"],
                        "score": d["metadata"]["score"],
                        "rerank_score": d["metadata"].get("rerank_score"),
                    }
                    for d in docs[:10]
                ]

            mapping_standardizations = [
                {"abbreviation": r["abbreviation"], "expansion": r["expansion"], "candidates": r["std_cache"]}
                for r in pending
            ]
            verification = self.verifier.verify_mappings(
                original_text=text, expanded_text=current_expanded_text,
                mapping_standardizations=mapping_standardizations,
            )
            validations = verification.get("mapping_validations", [])

            def _find_validation(rec):
                for v in validations:
                    if v.get("abbreviation") == rec["abbreviation"] and v.get("expansion") == rec["expansion"]:
                        return v
                return None

            # Coverage decides expansion; verify only chooses/withholds SNOMED coding.
            for r in pending:
                v = _find_validation(r)
                chosen_index = v.get("chosen_index") if v else None
                faithful = bool(v and v.get("standardization_faithful") is True)
                valid_index = (
                    faithful and isinstance(chosen_index, int) and not isinstance(chosen_index, bool)
                    and 0 <= chosen_index < len(r["std_cache"])
                )
                r["std_concept"] = r["std_cache"][chosen_index] if valid_index else None
                if r["std_concept"]:
                    r["status"] = "CODED"
                    r["failure"] = None
                else:
                    r["status"] = "WITHHELD"
                    r["failure"] = {
                        "type": "CODE_WITHHELD", "stage": "standardization",
                        "reason": (v.get("reason") if v else None) or "no faithful SNOMED concept among retrieved candidates",
                        "evidence": {"retrieved_top": [c.get("concept_name") for c in (r["std_cache"] or [])[:5]]},
                    }

            # batch10 standardization reflection may rescue WITHHELD into CODED.
            for r in pending:
                self._reflect_refine_standardization(r, text, current_expanded_text)
                if r.get("std_concept") and r["status"] == "WITHHELD":
                    r["status"] = "CODED"
                    r["failure"] = None

            for item in mapping_standardizations:
                rec = next(
                    r for r in pending
                    if r["abbreviation"] == item["abbreviation"] and r["expansion"] == item["expansion"]
                )
                item["chosen_concept"] = rec["std_concept"]

            current_expanded_text = self._build_expanded_text_deterministic(text, _visible(records))

            attempts.append({
                "attempt": attempt_index + 1,
                "expanded_text": current_expanded_text,
                "abbreviation_candidates": current_abbreviation_candidates,
                "mappings": [
                    {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                     "label": r["label"], "source": r["source"], "status": r["status"]}
                    for r in records
                ],
                "mapping_standardizations": mapping_standardizations,
                "verification": verification,
            })

        # Loop end: any still-PENDING record abstains safely.
        for r in records:
            if r["status"] == "PENDING":
                r["status"] = "ABSTAIN"
                r["failure"] = {
                    "type": "EXPANSION_ABSTAIN", "stage": "coverage",
                    "reason": "expansion candidates exhausted without a lock", "evidence": {},
                }

        # Final output: preserve the previous public response fields.
        current_expanded_text = self._build_expanded_text_deterministic(text, _visible(records))
        resolved = [r for r in records if r["status"] in ("CODED", "WITHHELD")]
        final_mappings = [
            {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
             "label": r["label"], "source": r["source"], "status": r["status"]}
            for r in resolved
        ]
        success_breakdown = self._build_success_breakdown(records)
        expansion_success = success_breakdown["expansion_success"]
        standardization_success = success_breakdown["standardization_success"]
        success = expansion_success and standardization_success

        final_result = {
            "attempt": len(attempts),
            "expanded_text": current_expanded_text,
            "abbreviation_candidates": current_abbreviation_candidates,
            "mappings": final_mappings,
            "mapping_standardizations": [
                {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                 "candidates": r["std_cache"], "chosen_concept": r["std_concept"]}
                for r in resolved
            ],
            "verification": attempts[-1]["verification"] if attempts else None,
            "mapping_states": [
                {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                 "source": r["source"], "status": r["status"],
                 "domain": r.get("domain"),
                 "chosen_concept": r.get("std_concept"),
                 "coverage": r["coverage"], "failure": r["failure"]}
                for r in records
            ],
            "success_breakdown": success_breakdown,
        }

        log_pipeline(
            "pipeline.final",
            component="ABBRService",
            duration_ms=round((time.perf_counter() - pipeline_start) * 1000, 2),
            success=success,
            expansion_success=expansion_success,
            standardization_success=standardization_success,
            attempt_count=len(attempts),
            target_count=success_breakdown["target_count"],
            expanded_count=success_breakdown["expanded_count"],
            coded_count=success_breakdown["coded_count"],
            withheld_count=success_breakdown["withheld_count"],
            not_expanded_count=success_breakdown["not_expanded_count"],
            mapping_count=len(final_mappings),
            ok=True,
        )
        return {
            "original_text": text,
            "final_expanded_text": current_expanded_text,
            "success": success,
            "expansion_success": expansion_success,
            "standardization_success": standardization_success,
            "success_breakdown": success_breakdown,
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

        reload_abbr_candidates_if_changed()
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
            retrieval_trace = {
                "primary_called": True,
                "primary_candidate_count": len(candidates or []),
                "fallback_called": False,
                "fallback_candidate_count": None,
                "fallback_reason": None,
                "fallback_error_kind": None,
                "fallback_raw_output": None,
                "fallback_error": None,
            }
            candidate_source = "primary"

            #第二层：如果主候选库没有结果，走fallback retriever
            if not candidates:
                fallback_result = self.fallback_retriever.retrieve(
                    abbreviation=abbr,
                    context_text=text
                )
                candidates = fallback_result.get("candidates",[])
                retrieval_trace.update({
                    "fallback_called": True,
                    "fallback_candidate_count": len(candidates or []),
                    "fallback_reason": fallback_result.get("reason"),
                    "fallback_error_kind": fallback_result.get("error_kind"),
                    "fallback_raw_output": fallback_result.get("raw_output"),
                    "fallback_error": fallback_result.get("error"),
                })
                candidate_source = "fallback"

            if candidate_source == "fallback":
                for candidate in candidates:
                    domain, _, _ = self.ner_service.infer_domain(candidate.get("expansion"))
                    candidate["domain"] = domain
            
            #如果primary和fallback都没有候选
            if not candidates:
                coverage = {
                    "abbreviation": abbr,
                    "coverage_ok": False,
                    "confidence": 0.0,
                    "plausible_candidates": [],
                    "reason": "No candidates found from primary or fallback retriever.",
                    "issues": ["no_candidates"]
                }
                found.append({
                    "abbreviation":abbr,
                    "candidates": [],
                    "filtered_candidates": [],
                    "coverage": coverage,
                    "candidate_source": "none",
                    "best_expansion": None,
                    "chosen_label": None,
                    "chosen_domain": None,
                    "resolution": "not_expanded",
                    "failure": self._build_not_expanded_failure(
                        abbr=abbr,
                        candidates=[],
                        coverage=coverage,
                        candidate_source="none",
                        retrieval_trace=retrieval_trace,
                    )
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
            failure = None
            resolution = "expanded" if best else "not_expanded"
            if not best:
                failure = self._build_not_expanded_failure(
                    abbr=abbr,
                    candidates=candidates,
                    coverage=coverage,
                    candidate_source=candidate_source,
                    retrieval_trace=retrieval_trace,
                )

            found.append({
                "abbreviation":abbr,
                "candidates":candidates,
                "filtered_candidates":filtered_candidates,
                "coverage":coverage,
                "candidate_source":candidate_source,
                "best_expansion":best,
                "chosen_label":None,
                "chosen_domain":best_domain,
                "resolution": resolution,
                "failure": failure
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
