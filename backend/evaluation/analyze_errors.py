"""
Analyze the unified error JSONL store.

Run `python backend/evaluation/run_benchmark.py` first so runtime failures and
gold mismatches can be collected into backend/logs/unresolved_cases.jsonl.
"""
import json
from collections import Counter
from pathlib import Path


LOG = Path(__file__).resolve().parents[1] / "logs" / "unresolved_cases.jsonl"


def main():
    if not LOG.exists():
        print(f"No error log found: {LOG}")
        print("Run `python backend/evaluation/run_benchmark.py` first.")
        return

    recs = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"Total error records: {len(recs)}\n")

    def dist(title, counter, n=10):
        print(title)
        for k, c in counter.most_common(n):
            print(f"  {c:>4}  {k}")
        print()

    dist(
        "By failure_type (runtime known-unknowns + GOLD_MISMATCH):",
        Counter(r["failure_type"] for r in recs),
    )
    dist(
        "Top abbreviations:",
        Counter(r.get("abbreviation") for r in recs if r.get("abbreviation")),
    )
    dist(
        "Top withheld expansions (CODE_WITHHELD):",
        Counter(
            r.get("expansion")
            for r in recs
            if r["failure_type"] == "CODE_WITHHELD" and r.get("expansion")
        ),
    )
    dist("By source:", Counter(r.get("source") for r in recs))
    dist("By stage:", Counter(r.get("stage") for r in recs))

    print("One sample per failure_type:")
    seen = set()
    for r in recs:
        failure_type = r["failure_type"]
        if failure_type in seen:
            continue
        seen.add(failure_type)
        print(
            f"  [{failure_type}] abbr={r.get('abbreviation')} "
            f"exp={r.get('expansion')} src={r.get('source')}"
        )
        print(f"        reason={r.get('reason')}  evidence={r.get('evidence')}")


if __name__ == "__main__":
    main()
