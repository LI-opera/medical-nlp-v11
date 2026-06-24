import datetime
import json
import os
from pathlib import Path


DEFAULT_LOG = Path(__file__).resolve().parents[1] / "logs" / "unresolved_cases.jsonl"


def _runtime_on():
    return os.getenv("ERROR_LOG_RUNTIME", "1") != "0"


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


def _expected_for(failure_type, abbreviation, gold_abbrs):
    if gold_abbrs is None:
        return None
    abbr = (abbreviation or "").upper()
    if failure_type in ("ABBR_NOT_EXPANDED", "EXPANSION_ABSTAIN", "COVERAGE_FAILED"):
        return abbr not in gold_abbrs
    return None


def collect_unresolved(text, records, source="runtime", gold_abbrs=None, log_path=None):
    """Collect all failure records and annotate gold-derived expected when available."""
    try:
        if source == "runtime" and not _runtime_on():
            return
        rows = []
        for r in records or []:
            f = r.get("failure")
            if not f:
                continue
            ftype = f.get("type")
            rows.append({
                "ts": _now(),
                "text": text,
                "source": source,
                "failure_type": f.get("type"),
                "stage": f.get("stage"),
                "abbreviation": r.get("abbreviation"),
                "expansion": r.get("expansion"),
                "reason": f.get("reason"),
                "evidence": f.get("evidence"),
                "expected": _expected_for(ftype, r.get("abbreviation"), gold_abbrs),
            })
        if records and not any(r.get("expansion") for r in records):
            whole = None if gold_abbrs is None else (len(gold_abbrs) == 0)
            rows.append({
                "ts": _now(),
                "text": text,
                "source": source,
                "failure_type": "COVERAGE_FAILED",
                "stage": "coverage",
                "abbreviation": None,
                "expansion": None,
                "reason": "no abbreviation produced a usable expansion",
                "evidence": {"abbreviations": [r.get("abbreviation") for r in records]},
                "expected": whole,
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
            "expected": False,
        }], log_path)
    except Exception:
        pass
