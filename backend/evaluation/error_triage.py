"""
Offline LLM error triage.

Reads backend/logs/unresolved_cases.jsonl, clusters records deterministically,
then asks an LLM for grounded root-cause hypotheses, levers, cited records,
verification plans, fix sketches, and candidate gold-case drafts.

Guardrails:
1. Offline only: this script is not imported by the main pipeline, API, or scoring.
2. LLM proposes hypotheses only. It never mutates code, benchmark gold, or logs used
   for scoring. Human review plus benchmark adjudication decides any follow-up.
3. Clusters with fewer than 3 records are low-confidence by default; do not treat
   thin evidence as a pattern.

Run:
    python backend/evaluation/error_triage.py

Requires:
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
- confidence: "high" | "medium" | "low"
  Use "low" if fewer than 3 records support the pattern.
- how_to_verify: concrete benchmark case or measurement that would confirm/refute it
- fix_sketch: candidate fix direction mapped to the lever; this is only a hypothesis
- gold_case_drafts: draft benchmark cases that would harden against this, may be []
  For stage "expansion":
    {{"target":"main","text":"...","expected_mappings":[{{"abbreviation":"..","expansion":".."}}]}}
  For stage "standardization":
    {{"target":"concept","label":"..","expansion":"..","prefer":"..","accept":[".."]}}

Do NOT invent facts beyond the records.
If evidence is thin, say so via low confidence.
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
            "root_cause": f"LLM or JSON parsing failed: {exc}",
            "lever": "other",
            "supporting_records": [],
            "confidence": "low",
            "how_to_verify": "",
            "fix_sketch": "",
            "gold_case_drafts": [],
        }]


def _markdown_list(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def main():
    records = load_records()
    if not records:
        print(f"No error log found or log is empty: {LOG}")
        print("Run `python backend/evaluation/run_benchmark.py` after batch11B first.")
        return

    groups = cluster(records)
    model = make_llm()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Error Triage Report (LLM hypotheses; benchmark adjudicates)",
        "",
        f"> Records: {len(records)}. Clusters: {len(groups)}.",
        "> The following items are hypotheses only. Do not auto-change code or gold.",
        "> Human review plus benchmark evidence decides any follow-up.",
    ]
    all_drafts = []

    sorted_groups = sorted(groups.items(), key=lambda item: (-len(item[1]), str(item[0])))
    for (failure_type, stage), group_records in sorted_groups:
        lines.append("")
        lines.append(f"## Cluster: {failure_type} / {stage} ({len(group_records)} records)")
        if len(group_records) < MIN_CONFIDENT:
            lines.append(
                f"> Low-confidence cluster by size: fewer than {MIN_CONFIDENT} records. "
                "Treat as a candidate signal, not a pattern."
            )

        patterns = analyze_cluster(model, failure_type, stage, group_records)
        for pattern_index, pattern in enumerate(patterns, start=1):
            supporting = pattern.get("supporting_records") or []
            if len(supporting) < MIN_CONFIDENT:
                pattern["confidence"] = "low"

            lines.append("")
            lines.append(f"### Pattern {pattern_index}")
            lines.append(f"- Root-cause hypothesis: {_markdown_list(pattern.get('root_cause'))}")
            lines.append(f"- Lever: `{_markdown_list(pattern.get('lever'))}`")
            lines.append(f"- Confidence: `{_markdown_list(pattern.get('confidence'))}`")
            lines.append(f"- Supporting records in cluster: `{_markdown_list(supporting)}`")
            lines.append(f"- How to verify: {_markdown_list(pattern.get('how_to_verify'))}")
            lines.append(f"- Fix sketch (hypothesis only): {_markdown_list(pattern.get('fix_sketch'))}")

            drafts = pattern.get("gold_case_drafts") or []
            if drafts:
                lines.append(
                    f"- Candidate gold-case drafts: {len(drafts)} "
                    f"(see `{CANDIDATE_GOLD.name}`; use only after human+benchmark adjudication)"
                )
                all_drafts.extend(drafts)

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    CANDIDATE_GOLD.write_text(
        json.dumps(all_drafts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("Wrote triage outputs:")
    print(f"  report: {REPORT}")
    print(f"  candidate gold drafts: {CANDIDATE_GOLD} ({len(all_drafts)} records)")
    print("Reminder: LLM proposes; benchmark adjudicates. No code or gold was modified.")


if __name__ == "__main__":
    main()
