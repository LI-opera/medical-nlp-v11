"""
L3 Stage-5: 多源 A/B 量化

对每个药品扩写，分别强制走 SNOMED 和 RxNorm，跑 检索 top-10 → verify 选概念，
并排打印：选中概念名 / concept_code / domain_id / top1 相似分 / 是否弃码。

目的：诚实回答“路由到 RxNorm 相对只用 SNOMED 到底改变了什么”。
跑法：python backend/evaluation/run_source_ab.py（需 Milvus + DeepSeek key）
"""
import os
import sys
from pathlib import Path

os.environ["ERROR_LOG_RUNTIME"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from services.abbr_service import ABBRService


DRUGS = [
    "aspirin",
    "methotrexate",
    "acetaminophen",
    "hydrochlorothiazide",
    "nitroglycerin",
]
TOP_K = 10
SCORE_TH = 0.6


def _top1_score(doc):
    if not doc:
        return None
    score = doc.get("score")
    if score is None:
        score = (doc.get("metadata") or {}).get("score")
    return round(score, 4) if isinstance(score, (int, float)) else score


def run_one(svc, expansion, source):
    docs = svc.retriever.retrieve(
        query=expansion,
        top_k=TOP_K,
        domain_filter=None,
        score_threshold=SCORE_TH,
        source=source,
    )
    cands = [d["metadata"] for d in docs]
    res = svc.verifier.verify_mappings(
        original_text=f"The patient took {expansion}.",
        expanded_text=f"The patient took {expansion}.",
        mapping_standardizations=[{
            "abbreviation": expansion,
            "expansion": expansion,
            "candidates": cands,
        }],
    )
    mv = (res.get("mapping_validations") or [{}])[0]
    ci = mv.get("chosen_index")
    chosen = None
    if (
        isinstance(ci, int)
        and not isinstance(ci, bool)
        and 0 <= ci < len(cands)
        and mv.get("standardization_faithful") is True
    ):
        chosen = cands[ci]
    return {
        "n_cands": len(cands),
        "top1_score": _top1_score(docs[0] if docs else None),
        "name": chosen.get("concept_name") if chosen else None,
        "code": chosen.get("concept_code") if chosen else None,
        "domain": chosen.get("domain_id") if chosen else None,
    }


def main():
    svc = ABBRService()
    print(f"{'drug':<20}{'source':<8}{'chosen':<28}{'code':<10}{'domain':<14}{'top1':<8}")
    print("-" * 88)
    for drug in DRUGS:
        for source in ("snomed", "rxnorm"):
            r = run_one(svc, drug, source)
            name = r["name"] if r["name"] else "(弃码)"
            print(
                f"{drug:<20}{source:<8}{name:<28}"
                f"{str(r['code']):<10}{str(r['domain']):<14}{str(r['top1_score']):<8}"
            )
        print()


if __name__ == "__main__":
    main()
