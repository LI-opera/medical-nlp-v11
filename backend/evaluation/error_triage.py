"""
离线 LLM 错误 Triage。

读取 backend/logs/unresolved_cases.jsonl，先按读时规则隐藏 expected=True
的“预期内正确弃权”，再按 (failure_type, stage) 聚类，让 LLM 基于真实
错误记录生成根因假设、杠杆、引用记录、验证方法、修复草图和候选 gold 用例。

铁律：
1. 离线：本脚本不被主链路 / API / benchmark 判分导入。
2. LLM 只提出假设，绝不自动改代码、gold 或判分日志；一切由人工 + benchmark 裁决。
3. 簇或支撑记录少于 3 条默认低置信，不能把噪声当模式。
4. 写入端不删数据；expected=True 只在读取分析时默认隐藏，仍可从原日志回溯。

运行：
    python backend/evaluation/error_triage.py

依赖：
    backend/logs/unresolved_cases.jsonl
    DEEPSEEK_API_KEY
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

LEVERS = "dictionary | lib_coverage | retrieval | verify_rubric | gold_labeling | other"


def load_records():
    if not LOG.exists():
        return []
    return [
        json.loads(line)
        for line in LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def cluster(records):
    groups = defaultdict(list)
    for record in records:
        groups[(record.get("failure_type"), record.get("stage"))].append(record)
    return groups


def make_llm():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is not set.")
    return ChatDeepSeek(
        model="deepseek-chat",
        api_key=api_key,
        temperature=0,
        max_retries=2,
    )


def _clean_json_content(content):
    return content.strip().replace("```json", "").replace("```", "").strip()


def analyze_cluster(model, failure_type, stage, records):
    sample = records[:20]
    payload = [
        {
            "i": index,
            "abbreviation": record.get("abbreviation"),
            "expansion": record.get("expansion"),
            "source": record.get("source"),
            "reason": record.get("reason"),
            "evidence": record.get("evidence"),
            "expected": record.get("expected"),
        }
        for index, record in enumerate(sample)
    ]
    prompt = f"""You are a triage analyst for a medical-abbreviation NLP pipeline.

You are given a CLUSTER of failure records:
- failure_type: {failure_type}
- stage: {stage}

Map each root cause to EXACTLY one pipeline lever:
  {LEVERS}

Lever definitions:
- dictionary: abbreviation/expansion dictionary missing an entry or sense
- lib_coverage: the SNOMED concept library lacks a faithful concept
- retrieval: retrieval/rerank/window buried or missed a concept that exists
- verify_rubric: the verify selection/abstain rule chose wrong or over-withheld
- gold_labeling: the benchmark gold label itself looks wrong or too strict
- other: none of the above

Records are indexed by i:
{json.dumps(payload, ensure_ascii=False, indent=2)}

Identify 1-3 root-cause PATTERNS. For each pattern return:
- root_cause: one sentence, grounded ONLY in these records
- lever: one of the allowed levers
- supporting_records: list of real record indices i that support it
- confidence: "high" | "medium" | "low"  (use "low" if fewer than 3 records support it)
- how_to_verify: concrete benchmark case or measurement that would confirm/refute it
- fix_sketch: candidate fix direction mapped to the lever; this is only a hypothesis
- gold_case_drafts: draft benchmark cases that would harden against this, may be []
  For stage "expansion":
    {{"target":"main","text":"...","expected_mappings":[{{"abbreviation":"..","expansion":".."}}]}}
  For stage "standardization":
    {{"target":"concept","label":"..","expansion":"..","prefer":"..","accept":[".."]}}

IMPORTANT - LANGUAGE: write root_cause, how_to_verify, and fix_sketch in SIMPLIFIED CHINESE.
Keep `lever` and `confidence` as the given English enum values. Keep JSON keys in English.

Do NOT invent facts beyond the records. If evidence is thin, say so via low confidence.
Return raw valid JSON only in this shape:
{{"patterns":[ ... ]}}"""
    try:
        response = model.invoke(prompt)
        content = _clean_json_content(response.content)
        parsed = json.loads(content)
        patterns = parsed.get("patterns", [])
        return patterns if isinstance(patterns, list) else []
    except Exception as exc:
        return [{
            "root_cause": f"LLM 调用或 JSON 解析失败: {exc}",
            "lever": "other",
            "supporting_records": [],
            "confidence": "low",
            "how_to_verify": "",
            "fix_sketch": "",
            "gold_case_drafts": [],
        }]


def _md(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def main():
    records = load_records()
    if not records:
        print(f"未找到错误日志或日志为空: {LOG}")
        print("先运行 `python backend/evaluation/run_benchmark.py` 产生错误记录。")
        return

    raw_n = len(records)
    records = [r for r in records if r.get("expected") is not True]
    hidden = raw_n - len(records)

    groups = cluster(records)
    model = make_llm()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 错误 Triage 报告（LLM 提假设，benchmark 裁决）",
        "",
        f"> 原始日志 {raw_n} 条；已自动隐藏 {hidden} 条 expected=True 的 gold 确定正确弃权；当前分析 {len(records)} 条、{len(groups)} 个簇。",
        "> 全量数据仍保留在 unresolved_cases.jsonl 中，可回溯；这里的过滤只是读时决策。",
        "> 以下全部是【假设草图】，不自动改代码或 gold；一切以人工复核 + benchmark 证据为准。",
    ]
    all_drafts = []

    sorted_groups = sorted(groups.items(), key=lambda item: (-len(item[1]), str(item[0])))
    for (failure_type, stage), group_records in sorted_groups:
        lines.append("")
        lines.append(f"## 簇：{failure_type} / {stage}（{len(group_records)} 条）")
        if len(group_records) < MIN_CONFIDENT:
            lines.append(
                f"> 样本少于 {MIN_CONFIDENT} 条，默认低置信；只能当线索看，不能当定论。"
            )

        patterns = analyze_cluster(model, failure_type, stage, group_records)
        for pattern_index, pattern in enumerate(patterns, start=1):
            supporting = pattern.get("supporting_records") or []
            if len(supporting) < MIN_CONFIDENT:
                pattern["confidence"] = "low"

            lines.append("")
            lines.append(f"### 模式 {pattern_index}")
            lines.append(f"- 根因假设：{_md(pattern.get('root_cause'))}")
            lines.append(f"- 杠杆（改哪里）：`{_md(pattern.get('lever'))}`")
            lines.append(f"- 置信：`{_md(pattern.get('confidence'))}`")
            lines.append(f"- 支撑记录（簇内 index）：`{_md(supporting)}`")
            lines.append(f"- 如何验证：{_md(pattern.get('how_to_verify'))}")
            lines.append(f"- 修复方向（仅假设，先证后建）：{_md(pattern.get('fix_sketch'))}")

            drafts = pattern.get("gold_case_drafts") or []
            if drafts:
                lines.append(
                    f"- 候选 gold 用例草稿：{len(drafts)} 条 "
                    f"（见 `{CANDIDATE_GOLD.name}`；人工 + benchmark 裁决后才可用）"
                )
                all_drafts.extend(drafts)

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    CANDIDATE_GOLD.write_text(
        json.dumps(all_drafts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("已写出 triage 产物:")
    print(f"  报告: {REPORT}")
    print(f"  候选 gold 草稿: {CANDIDATE_GOLD}（共 {len(all_drafts)} 条）")
    print("提醒: LLM 只提假设，benchmark 裁决；未改任何代码或 gold。")


if __name__ == "__main__":
    main()
