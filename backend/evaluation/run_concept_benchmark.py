"""
Concept 层 benchmark runner(标准化层评测)
================================================================
对每条 gold:给定【正确扩写】→ 检索 top-10 → verify 选概念,
判选中的概念名是否 ∈ {prefer}∪accept(或该弃码时是否弃码)。

复刻的是主链路标准化那一步(状态机 docs[:10] → verify chosen_index),
所以测到的就是批次8 verify 实际产出、以及 batch9 会改动的那一层。
注:这里直接喂【正确扩写】、绕过 coverage——本层只测标准化,不测消歧。

跑法:python backend/evaluation/run_concept_benchmark.py
需要 Milvus + DeepSeek key(和 benchmark 同环境)。
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from evaluation.concept_benchmark_cases import CONCEPT_BENCHMARK_CASES
from services.abbr_service import ABBRService

TOP_K = 10            # 与主链路状态机 docs[:10] 一致
SCORE_TH = 0.6


def _norm(s):
    return s.strip().lower() if isinstance(s, str) else s


def judge(case, chosen_name):
    """返回 (passed, canonical_hit, verdict_str)。"""
    if case["expect"] == "abstain":
        passed = chosen_name is None
        return passed, False, ("弃码 OK" if passed else f"该弃码却选了 {chosen_name!r}")
    # expect concept
    accept_norm = {_norm(case["prefer"])} | {_norm(a) for a in case.get("accept", [])}
    if chosen_name is None:
        return False, False, "该给码却弃码"
    if _norm(chosen_name) not in accept_norm:
        return False, False, f"选了 {chosen_name!r}(不在 accept 内)"
    canonical = _norm(chosen_name) == _norm(case["prefer"])
    return True, canonical, ("canonical(最规范)" if canonical else f"acceptable(非最规范)")


def show(rows, title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    for case, chosen, faithful, reason, passed, canonical, verdict in rows:
        flag = "PASS" if passed else "FAIL"
        exp_str = "弃码" if case["expect"] == "abstain" else f"prefer={case['prefer']!r}"
        print(f"[{flag}] {case['label']:<12} {case['expansion']!r}")
        print(f"        期望: {exp_str}   →  {verdict}")
        print(f"        选中: {chosen!r}  faithful={faithful}")
        if (not passed) or (not canonical):
            print(f"        reason: {reason}")


def main():
    svc = ABBRService()

    conf_total = conf_pass = conf_canon = 0
    rows_conf, rows_unconf = [], []

    for case in CONCEPT_BENCHMARK_CASES:
        original_text = f"The patient has {case['expansion']}."
        expanded_text = f"The patient has {case['expansion']}."
        cands = [
            d["metadata"]
            for d in svc.retriever.retrieve(
                query=case["expansion"],
                top_k=TOP_K,
                domain_filter=None,
                score_threshold=SCORE_TH,
            )
        ]
        res = svc.verifier.verify_mappings(
            original_text=original_text,
            expanded_text=expanded_text,
            mapping_standardizations=[{
                "abbreviation": case["label"],
                "expansion": case["expansion"],
                "candidates": cands,
            }],
        )
        mv = (res.get("mapping_validations") or [{}])[0]
        ci = mv.get("chosen_index")
        init = cands[ci] if (
            isinstance(ci, int)
            and not isinstance(ci, bool)
            and 0 <= ci < len(cands)
            and mv.get("standardization_faithful") is True
        ) else None
        s = {
            "abbreviation": case["label"],
            "expansion": case["expansion"],
            "std_cache": cands,
            "std_concept": init,
            "domain": None,
        }
        svc._reflect_refine_standardization(s, original_text, expanded_text)
        chosen = s["std_concept"]["concept_name"] if s.get("std_concept") else None
        faithful = bool(s.get("std_concept"))
        reason = mv.get("reason")
        passed, canonical, verdict = judge(case, chosen)
        if case.get("confirmed") and not passed:
            try:
                from services.error_collector import collect_gold_mismatch
                collect_gold_mismatch(
                    text=case["expansion"],
                    stage="standardization",
                    source="benchmark:concept",
                    expected={"prefer": case["prefer"], "accept": case.get("accept", [])},
                    predicted=chosen,
                    abbreviation=case["label"],
                )
            except Exception:
                pass
        row = (case, chosen, faithful, reason, passed, canonical, verdict)
        if case.get("confirmed"):
            rows_conf.append(row)
            conf_total += 1
            conf_pass += int(passed)
            conf_canon += int(canonical)
        else:
            rows_unconf.append(row)

    show(rows_conf, "① 硬 gold(计入准确率)")
    show(rows_unconf, "② 待锁定假设(只打印,首跑后据实补/改 gold)")

    print("\n" + "=" * 72)
    print("==== Concept-层 标准化准确率(仅 confirmed)====")
    if conf_total:
        print(f"  PASS(忠实命中)   : {conf_pass}/{conf_total} = {conf_pass / conf_total:.4f}")
        print(f"  canonical(最规范) : {conf_canon}/{conf_total} = {conf_canon / conf_total:.4f}")
        print(f"  可升级空间(acceptable 但非 canonical,batch9 目标): {conf_pass - conf_canon}")
    print("  注:PASS 看忠实度,canonical 看规范度;两者差 = reflection/改写能改善的余量。")


if __name__ == "__main__":
    main()
