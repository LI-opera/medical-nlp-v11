# 批次 12 · 给 Codex 的指令(可整段复制)· LLM 错误 Triage(离线、提假设、benchmark 裁决)

## 背景与范围

batch11B 把错误攒进 `backend/logs/unresolved_cases.jsonl`(运行时弃码 + GOLD_MISMATCH)。本批建一个**离线 triage 工具**:确定性聚类 → LLM 对每簇出【根因假设 + 杠杆 + 引用记录 + 如何验证 + 修复草图 + 候选 gold 用例】→ 渲染报告 + 导出候选用例草稿。

**三条铁律(必须在代码与文档体现)**:
1. **离线工具,绝不进主链路/推理**;不改任何现有判分/状态机/API。
2. **LLM 只产【假设/草稿】**,绝不自动改 gold、不自动改代码;一切先证后建,人工 + benchmark 裁决。
3. **簇 < 3 条标低置信**(防把噪声当模式);根因必须引用具体记录,证据不足就 low confidence。

> 依赖:先合入 11B + 跑一次 `run_benchmark.py` 把日志填上,再跑本工具。本批是新增独立脚本,**无 benchmark 门**(它不改系统);验收=能在已填日志上跑通并产出三件套。

工作在 `medical-refactor`。

## 铁律

1. **只新增** `backend/evaluation/error_triage.py` 一个文件;不动其它任何文件(`backend/logs/` 已被 11B 的 .gitignore 覆盖,输出不入库)。
2. LLM 客户端照 `abbr_verifier.py` 的写法(`ChatDeepSeek(model="deepseek-chat", temperature=0, max_retries=2)`,key 取 `DEEPSEEK_API_KEY`)。
3. LLM 调用包 try/except + 去 markdown + json 解析容错。

---

## A · 新建 `backend/evaluation/error_triage.py`

```python
"""
错误 Triage(离线 · LLM 提假设 · benchmark 裁决)
读 backend/logs/unresolved_cases.jsonl -> 确定性聚类 -> LLM 出根因假设/杠杆/引用/如何验证/
修复草图/候选 gold 用例 -> 渲染报告 + 候选用例草稿。

铁律:① 离线,不碰主链路;② LLM 只产【假设/草稿】,先证后建,人工+benchmark 裁决,
绝不自动改 gold 或代码;③ 簇 < 3 标低置信,别把噪声当模式。
跑法:python backend/evaluation/error_triage.py   (需 DEEPSEEK_API_KEY)
"""
import os
import sys
import json
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
CAND = OUT_DIR / "candidate_gold_cases.json"
MIN_CONFIDENT = 3

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


def analyze_cluster(model, ftype, stage, recs):
    sample = recs[:20]
    payload = [
        {"i": i, "abbreviation": r.get("abbreviation"), "expansion": r.get("expansion"),
         "source": r.get("source"), "reason": r.get("reason"), "evidence": r.get("evidence")}
        for i, r in enumerate(sample)
    ]
    prompt = f"""You are a triage analyst for a medical-abbreviation NLP pipeline.
You are given a CLUSTER of failure records (all failure_type={ftype}, stage={stage}).
Map each root cause to EXACTLY one pipeline lever:
  {LEVERS}
  - dictionary: abbreviation/expansion dictionary missing an entry or sense
  - lib_coverage: the SNOMED concept library lacks a faithful concept
  - retrieval: retrieval/rerank/window buried or missed a concept that exists
  - verify_rubric: the verify selection/abstain rule chose wrong or over-withheld
  - gold_labeling: the benchmark gold label itself looks wrong or too strict
  - other: none of the above

Records (index i : data):
{json.dumps(payload, ensure_ascii=False, indent=2)}

Identify 1-3 root-cause PATTERNS. For each return:
  - root_cause: one sentence, grounded ONLY in these records
  - lever: one of the allowed levers
  - supporting_records: list of indices i that support it (cite real ones)
  - confidence: "high" | "medium" | "low"  (use "low" if fewer than 3 records support it)
  - how_to_verify: the concrete benchmark case or measurement that would confirm/refute it
  - fix_sketch: a candidate fix DIRECTION mapped to the lever (a hypothesis, not a final answer)
  - gold_case_drafts: list of draft benchmark cases that would harden against this (may be empty);
      stage 'expansion' shape: {{"target":"main","text":"...","expected_mappings":[{{"abbreviation":"..","expansion":".."}}]}}
      stage 'standardization' shape: {{"target":"concept","label":"..","expansion":"..","prefer":"..","accept":[".."]}}
Do NOT invent facts beyond the records. If evidence is thin, say so via low confidence.
Return raw JSON only: {{"patterns":[ ... ]}}"""
    try:
        resp = model.invoke(prompt)
        content = resp.content.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(content).get("patterns", [])
    except Exception as e:
        return [{
            "root_cause": f"(LLM/parse failed: {e})", "lever": "other",
            "supporting_records": [], "confidence": "low",
            "how_to_verify": "", "fix_sketch": "", "gold_case_drafts": [],
        }]


def main():
    records = load_records()
    if not records:
        print(f"无错误日志 {LOG};先合入 11B + 跑 `python backend/evaluation/run_benchmark.py` 产出错误。")
        return
    groups = cluster(records)
    model = make_llm()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 错误 Triage 报告(LLM 提假设 · 先证后建)",
        "",
        f"> 共 {len(records)} 条错误、{len(groups)} 个簇。**以下均为假设/草稿,需 benchmark 裁决后才采纳;不自动改 gold 或代码。**",
    ]
    all_drafts = []
    for (ftype, stage), recs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"\n## 簇  {ftype} / {stage}  ({len(recs)} 条)")
        if len(recs) < MIN_CONFIDENT:
            lines.append(f"> ⚠ 样本少(<{MIN_CONFIDENT}),结论低置信,可能是噪声。")
        for p in analyze_cluster(model, ftype, stage, recs):
            lines.append(f"\n**根因假设**:{p.get('root_cause')}")
            lines.append(f"- 杠杆:`{p.get('lever')}`  |  置信:{p.get('confidence')}")
            lines.append(f"- 支撑记录(簇内 index):{p.get('supporting_records')}")
            lines.append(f"- 如何验证:{p.get('how_to_verify')}")
            lines.append(f"- 修复方向(草图,先证后建):{p.get('fix_sketch')}")
            drafts = p.get("gold_case_drafts") or []
            if drafts:
                lines.append(f"- 候选 gold 用例草稿:{len(drafts)} 条(见 {CAND.name},人工确认后才进 gold)")
                all_drafts.extend(drafts)

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    CAND.write_text(json.dumps(all_drafts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出:\n  报告        {REPORT}\n  候选用例草稿 {CAND}  ({len(all_drafts)} 条,人工+benchmark 裁决后再用)")


if __name__ == "__main__":
    main()
```

---

## 验收

1. **编译+import**:`python -m compileall backend/evaluation/error_triage.py` 通过。
2. **跑通**(先确保 11B 已合入且 `unresolved_cases.jsonl` 有内容):`python backend/evaluation/error_triage.py` → 在 `backend/logs/triage/` 产出 `error_triage_report.md` + `candidate_gold_cases.json`,无报错;报告里每条根因带【杠杆 + 支撑记录 + 如何验证】,小簇标了低置信。
3. **不碰系统**:确认本批没改任何其它文件;主链路/benchmark 不受影响(无需重跑判分)。
4. **判定**:1-3 全过 → 合入。

## 提交

```bash
git add backend/evaluation/error_triage.py
git commit -m "V11 batch12: offline LLM error triage. Cluster -> grounded root-cause hypotheses (lever + cited records + how-to-verify + fix sketch + candidate gold-case drafts). LLM proposes, benchmark disposes; never auto-mutates gold or code."
```
> 面试叙事:错误数据不是终点,是改进循环的入口。triage 把原始失败聚类、让 LLM 出**带引用、可证伪**的根因假设与候选护栏用例——但**裁决权永远在 benchmark**:LLM 提假设,benchmark 裁决。这条"提假设/裁决"分工和项目里 coverage→verify、retrieve→verify 是同一个哲学,贯穿到了 meta 层。诚实:数据量小时报告偏薄,价值随真实流量增长。
