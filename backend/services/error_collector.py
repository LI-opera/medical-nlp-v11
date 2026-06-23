"""
Unified error store.

Both runtime known-unknowns (record.failure) and benchmark gold mismatches are
written to one JSONL file. Collection is intentionally fail-safe: callers should
never let telemetry affect the main pipeline or scoring.
"""
import datetime
import json
from pathlib import Path


DEFAULT_LOG = Path(__file__).resolve().parents[1] / "logs" / "unresolved_cases.jsonl"


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _append(rows, log_path=None):
    if not rows:
        return
    path = Path(log_path) if log_path else DEFAULT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def collect_unresolved(text, records, log_path=None):
    """Collect runtime known-unknowns from unified records that carry failure."""
    try:
        rows = []
        for r in records or []:
            f = r.get("failure")
            if not f:
                continue
            rows.append({
                "ts": _now(),
                "text": text,
                "failure_type": f.get("type"),
                "stage": f.get("stage"),
                "abbreviation": r.get("abbreviation"),
                "expansion": r.get("expansion"),
                "source": r.get("source"),
                "reason": f.get("reason"),
                "evidence": f.get("evidence"),
            })
        if records and not any(r.get("expansion") for r in records):
            rows.append({
                "ts": _now(),
                "text": text,
                "failure_type": "COVERAGE_FAILED",
                "stage": "coverage",
                "abbreviation": None,
                "expansion": None,
                "source": None,
                "reason": "no abbreviation produced a usable expansion",
                "evidence": {"abbreviations": [r.get("abbreviation") for r in records]},
            })
        _append(rows, log_path)
    except Exception:
        pass


def collect_gold_mismatch(
    text,
    stage,
    source,
    expected,
    predicted,
    abbreviation=None,
    log_path=None,
):
    """Collect benchmark unknown-unknowns where prediction differs from gold."""
    try:
        _append([{
            "ts": _now(),
            "text": text,
            "failure_type": "GOLD_MISMATCH",
            "stage": stage,
            "abbreviation": abbreviation,
            "expansion": None,
            "source": source,
            "reason": "predicted != gold",
            "evidence": {"expected": expected, "predicted": predicted},
        }], log_path)
    except Exception:
        pass
