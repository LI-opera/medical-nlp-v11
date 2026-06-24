"""
离线 LLM 错误 Triage(三段式:LLM 提假设 → 数据自检 → LLM 据自检写执行摘要)。

  1) 读 unresolved_cases.jsonl,默认隐藏 expected=True(gold 确定的正确弃权),只分析真信号。
  2) 按 (failure_type, stage) 聚类;LLM(第1次)对每簇出根因假设 + checkable_claims。
  3) ★自检层(无 LLM):拿真实数据(Milvus 概念库 / 缩写词典)核每条 checkable_claim;
     被数据打脸的标 ⚠ 且不产草稿。
  4) ★总结层:LLM(第2次,仅1次)拿【已被数据判过的结论】写一份给非专业读者的中文执行摘要。
     —— 第2次 LLM 是"写作",不是"判断"(真假已由数据定),所以不是循环复判。

报告 = 顶部【执行摘要(好读)】+ 下部【逐假设自检原文(可追溯)】。
铁律:离线、不碰主链路;LLM 只提假设/做综述;草稿只在自检未被打脸时生成;绝不自动改代码/gold。
跑法:python backend/evaluation/error_triage.py  (需 DEEPSEEK_API_KEY + Milvus)
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env", override=True)

LOG = BACKEND_DIR / "logs" / "unresolved_cases.jsonl"
OUT_DIR = BACKEND_DIR / "logs" / "triage"
REPORT = OUT_DIR / "error_triage_report.md"
CANDIDATE_GOLD = OUT_DIR / "candidate_gold_cases.json"
MIN_CONFIDENT = 3
LIB_EXISTS_SCORE = 0.9

LEVERS = "dictionary | lib_coverage | retrieval | verify_rubric | gold_labeling | other"


def load_records():
    if not LOG.exists():
        return []
    return [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]


def cluster(records):
    groups = defaultdict(list)
    for r in records:
        groups[(r.get("failure_type"), r.get("stage"))].append(r)
    return groups


def make_llm():
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY is not set.")
    return ChatDeepSeek(model="deepseek-chat", api_key=key, temperature=0, max_retries=2)


def make_retriever():
    try:
        from services.medical_retriever import MedicalRetriever
        return MedicalRetriever()
    except Exception:
        return None


def _dict_present(abbr):
    try:
        from data.abbr_candidates import ABBR_CANDIDATES
        key = (abbr or "").upper()
        if key not in ABBR_CANDIDATES:
            return False, []
        exps = [c.get("expansion") if isinstance(c, dict) else c for c in ABBR_CANDIDATES[key]]
        return True, exps
    except Exception:
        return None, []


def verify_claim(retriever, claim):
    kind = claim.get("kind")
    value = (claim.get("value") or "").strip()
    if not value:
        return {"kind": kind, "value": value, "exists": None, "detail": "空断言,跳过"}
    if kind == "lib_concept":
        if retriever is None:
            return {"kind": kind, "value": value, "exists": None, "detail": "Milvus 不可用,无法自检"}
        try:
            docs = retriever.retrieve(query=value, top_k=3, domain_filter=None, score_threshold=0.0)
        except Exception as e:
            return {"kind": kind, "value": value, "exists": None, "detail": f"检索出错:{e}"}
        if not docs:
            return {"kind": kind, "value": value, "exists": False, "detail": "库里检索不到"}
        top = docs[0]["metadata"]
        score = float(top.get("score") or 0)
        exists = (top["concept_name"].strip().lower() == value.lower()) or (score >= LIB_EXISTS_SCORE)
        return {"kind": kind, "value": value, "exists": exists,
                "detail": f"库里 top1={top['concept_name']!r} score={round(score, 3)}"}
    if kind == "dict_abbr":
        present, exps = _dict_present(value)
        if present is None:
            return {"kind": kind, "value": value, "exists": None, "detail": "词典读取失败"}
        return {"kind": kind, "value": value, "exists": present,
                "detail": f"词典{'有' if present else '无'}: {exps}"}
    return {"kind": kind, "value": value, "exists": None, "detail": "未知断言类型,无法自检"}


def _contradicts(lever, check):
    if check.get("exists") is None:
        return None
    if lever == "lib_coverage" and check.get("kind") == "lib_concept":
        return check["exists"] is True
    if lever == "dictionary" and check.get("kind") == "dict_abbr":
        return check["exists"] is True
    return None


def analyze_cluster(model, failure_type, stage, records):
    sample = records[:20]
    payload = [
        {"i": i, "abbreviation": r.get("abbreviation"), "expansion": r.get("expansion"),
         "source": r.get("source"), "reason": r.get("reason"), "evidence": r.get("evidence")}
        for i, r in enumerate(sample)
    ]
    prompt = f"""You are a triage analyst for a medical-abbreviation NLP pipeline.

CLUSTER: failure_type={failure_type}, stage={stage}
Levers: {LEVERS}
- dictionary: abbr/expansion dictionary missing an entry/sense
- lib_coverage: the SNOMED concept library lacks a faithful concept
- retrieval: retrieval/rerank/window buried/missed a concept that exists
- verify_rubric: the verify selection/abstain rule chose wrong or over-withheld
- gold_labeling: the benchmark gold label itself looks wrong or too strict
- other

Records (index i):
{json.dumps(payload, ensure_ascii=False, indent=2)}

Identify 1-3 PATTERNS. For each return:
- root_cause, lever, supporting_records (i list), confidence (high|medium|low; low if <3)
- how_to_verify, fix_sketch
- checkable_claims: machine-checkable assertions your hypothesis depends on:
    {{"kind":"lib_concept","value":"<exact concept name claimed MISSING from SNOMED lib>"}}
    or {{"kind":"dict_abbr","value":"<abbreviation claimed MISSING from dictionary>"}}  (may be [])
- gold_case_drafts (may be []):
    stage "expansion": {{"target":"main","text":"...","expected_mappings":[{{"abbreviation":"..","expansion":".."}}]}}
    stage "standardization": {{"target":"concept","label":"..","expansion":"..","prefer":"..","accept":[".."]}}

LANGUAGE: root_cause/how_to_verify/fix_sketch in SIMPLIFIED CHINESE. lever/confidence/kind English. JSON keys English.
No facts beyond records. Return raw JSON only: {{"patterns":[ ... ]}}"""
    try:
        resp = model.invoke(prompt)
        content = resp.content.strip().replace("```json", "").replace("```", "").strip()
        pats = json.loads(content).get("patterns", [])
        return pats if isinstance(pats, list) else []
    except Exception as exc:
        return [{"root_cause": f"LLM 调用或解析失败: {exc}", "lever": "other", "supporting_records": [],
                 "confidence": "low", "how_to_verify": "", "fix_sketch": "",
                 "checkable_claims": [], "gold_case_drafts": []}]


def summarize(model, items):
    """第2次 LLM:据【已被数据判过的】结论写非专业读者可读的中文执行摘要。"""
    if not items:
        return "_(无可总结条目)_"
    prompt = f"""你是错误分析报告的总结员。下面是若干根因假设,每条的 status 已由【真实数据自检】判定(不是你判的):
- status=数据支持 / 无法验证 → 可能值得跟进
- status=数据矛盾 → 已被数据打脸,是假信号,必须当作【排除】,不得列为待办

给【非专业读者】写一份简短中文执行摘要(markdown 正文,别用代码块包裹),结构:
1. 开头一句话总览:共分析几条、其中值得跟进几条、排除几条假信号。
2. 「✅ 值得跟进」:把 status 非"数据矛盾"且像真问题的,每条用大白话写「问题是什么 + 建议下一步」,末尾注明「(需人工 + benchmark 裁决)」。
3. 「⚠ 已排除的假信号」:status=数据矛盾的,一句话说为什么不用管(数据显示其实已存在/不缺)。
4. 「◻ 需人工核」(若有):status=无法验证的,一句话点明要人去查什么。
要求:不夸大、不编造,只基于给定条目;被数据矛盾的明确写「排除」;优先日常话,少堆术语,短。

条目(JSON):
{json.dumps(items, ensure_ascii=False, indent=2)}"""
    try:
        resp = model.invoke(prompt)
        return resp.content.strip().replace("```markdown", "").replace("```", "").strip()
    except Exception as exc:
        return f"_(执行摘要生成失败:{exc};请看下方详细附录)_"


def _md(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def main():
    records = load_records()
    if not records:
        print(f"未找到错误日志或为空: {LOG};先跑 `python backend/evaluation/run_benchmark.py`。")
        return
    raw_n = len(records)
    records = [r for r in records if r.get("expected") is not True]
    hidden = raw_n - len(records)

    groups = cluster(records)
    model = make_llm()
    retriever = make_retriever()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    detail_lines = []     # 详细附录
    summary_items = []    # 喂给总结层
    all_drafts = []

    for (failure_type, stage), recs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
        detail_lines.append("")
        detail_lines.append(f"## 簇:{failure_type} / {stage}({len(recs)} 条)")
        if len(recs) < MIN_CONFIDENT:
            detail_lines.append(f"> ⚠ 样本少(<{MIN_CONFIDENT}),低置信。")

        for idx, p in enumerate(analyze_cluster(model, failure_type, stage, recs), start=1):
            supporting = p.get("supporting_records") or []
            if len(supporting) < MIN_CONFIDENT:
                p["confidence"] = "low"
            lever = p.get("lever")
            checks = [verify_claim(retriever, c) for c in (p.get("checkable_claims") or [])]
            contradicted = any(_contradicts(lever, c) is True for c in checks)
            verifiable = [c for c in checks if c.get("exists") is not None]
            status = "数据矛盾" if contradicted else ("数据支持" if verifiable else "无法验证")
            icon = {"数据矛盾": "⚠", "数据支持": "✅", "无法验证": "◻"}[status]

            detail_lines.append("")
            detail_lines.append(f"### 模式 {idx} —— {icon} {status}")
            detail_lines.append(f"- 根因假设:{_md(p.get('root_cause'))}")
            detail_lines.append(f"- 杠杆(改哪):`{_md(lever)}`  |  置信:`{_md(p.get('confidence'))}`")
            detail_lines.append(f"- 支撑记录(簇内 index):`{_md(supporting)}`")
            if checks:
                detail_lines.append("- 数据自检:")
                for c in checks:
                    mark = "  ← ⚠ 与假设矛盾" if _contradicts(lever, c) is True else ""
                    detail_lines.append(f"    - [{c.get('kind')}] {c.get('value')!r}: {c.get('detail')}{mark}")
            detail_lines.append(f"- 如何验证(人工):{_md(p.get('how_to_verify'))}")
            detail_lines.append(f"- 修复方向(仅假设,先证后建):{_md(p.get('fix_sketch'))}")

            drafts = p.get("gold_case_drafts") or []
            if drafts and not contradicted:
                detail_lines.append(f"- 候选 gold 用例草稿:{len(drafts)} 条(自检未被打脸)")
                all_drafts.extend(drafts)
            elif drafts and contradicted:
                detail_lines.append("- 候选 gold 用例草稿:已抑制(假设被数据打脸)")

            summary_items.append({
                "cluster": f"{failure_type}/{stage}",
                "status": status,
                "root_cause": p.get("root_cause"),
                "lever": lever,
                "confidence": p.get("confidence"),
                "support_count": len(supporting),
                "checks": [f"{c.get('value')}: {c.get('detail')}"
                           + ("(与假设矛盾)" if _contradicts(lever, c) is True else "")
                           for c in checks],
                "has_draft": bool(drafts and not contradicted),
            })

    summary_md = summarize(model, summary_items)

    head = [
        "# 错误 Triage 报告",
        "",
        f"> 全量 {raw_n} 条;隐藏 {hidden} 条【预期内】(gold 确定的正确弃权,非真错);分析 {len(records)} 条、{len(groups)} 个簇。",
        f"> 自检层:Milvus {'可用' if retriever else '不可用(概念库自检降级)'}。",
        "> 流程:LLM 提假设 → 真实数据自检 → LLM 据自检写摘要。全部是线索,不自动改代码/gold。",
        "",
        "## 执行摘要(给人看;基于数据自检结论)",
        "",
        summary_md,
        "",
        "---",
        "",
        "## 详细附录(逐假设 + 自检原文,可追溯)",
    ]
    REPORT.write_text("\n".join(head + detail_lines) + "\n", encoding="utf-8")
    CANDIDATE_GOLD.write_text(json.dumps(all_drafts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("已写出 triage 产物:")
    print(f"  报告(顶部执行摘要 + 详细附录):{REPORT}")
    print(f"  候选 gold 草稿:{CANDIDATE_GOLD}(共 {len(all_drafts)} 条;被打脸的假设不产草稿)")
    print("提醒:LLM 提假设 → 数据自检 → LLM 写摘要;未改任何代码或 gold。")


if __name__ == "__main__":
    main()
