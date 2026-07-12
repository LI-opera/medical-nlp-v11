import argparse
import ast
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent
sys.path.append(str(BACKEND_DIR))
from evaluation.paths import FALLBACK_PROMOTIONS_JSON_PATH

DEFAULT_INPUT = FALLBACK_PROMOTIONS_JSON_PATH
DEFAULT_CANDIDATES_FILE = BACKEND_DIR / "data" / "abbr_candidates.py"


def norm_abbr(value: Any) -> str:
    return str(value or "").strip().upper()


def norm_expansion(value: Any) -> str:
    return str(value or "").strip().lower()


def load_abbr_candidates(path: Path) -> dict[str, list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8")
    marker = "ABBR_CANDIDATES ="
    marker_index = text.index(marker)
    tree = ast.parse(text[marker_index:])
    assignment = tree.body[0]
    if not isinstance(assignment, ast.Assign):
        raise ValueError("ABBR_CANDIDATES assignment not found.")
    data = ast.literal_eval(assignment.value)
    return data


def load_approved_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("approved_items")
    if items is None:
        items = data.get("items", [])
    return items or []


def plan_items(
    candidates: dict[str, list[dict[str, Any]]],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    appended = []
    skipped = []

    for item in items:
        abbr = norm_abbr(item.get("abbreviation"))
        candidate = item.get("candidate_to_append") or {
            "expansion": item.get("expansion"),
            "domain": item.get("domain"),
        }
        expansion = str(candidate.get("expansion") or "").strip()
        domain = str(candidate.get("domain") or item.get("domain") or "Unknown").strip()

        if not abbr or not expansion:
            skipped.append({"item": item, "reason": "missing abbreviation or expansion"})
            continue

        existing = candidates.setdefault(abbr, [])
        exists = any(
            norm_expansion(entry.get("expansion")) == norm_expansion(expansion)
            for entry in existing
        )
        if exists:
            skipped.append(
                {
                    "abbreviation": abbr,
                    "expansion": expansion,
                    "reason": "already exists",
                }
            )
            continue

        new_candidate = {"expansion": expansion, "domain": domain}
        existing.append(new_candidate)
        appended.append({"abbreviation": abbr, "candidate": new_candidate})

    return {"appended": appended, "skipped": skipped}


def format_candidate(candidate: dict[str, Any]) -> str:
    expansion = json.dumps(candidate["expansion"], ensure_ascii=False)
    domain = json.dumps(candidate["domain"], ensure_ascii=False)
    return f'        {{"expansion": {expansion}, "domain": {domain}}},'


def find_abbr_block(lines: list[str], abbr: str) -> tuple[int, int] | None:
    start_prefix = f'    "{abbr}": ['
    for index, line in enumerate(lines):
        if line.startswith(start_prefix):
            for end in range(index + 1, len(lines)):
                if lines[end].startswith("    ],"):
                    return index, end
            raise ValueError(f"Could not find closing list for {abbr}.")
    return None


def find_candidates_dict_end(lines: list[str]) -> int:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() == "}":
            return index
    raise ValueError("Could not find ABBR_CANDIDATES closing brace.")


def apply_text_append(source: str, appended: list[dict[str, Any]], batch_note: str) -> str:
    lines = source.splitlines()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in appended:
        grouped.setdefault(item["abbreviation"], []).append(item["candidate"])

    existing_groups: dict[str, list[dict[str, Any]]] = {}
    new_groups: dict[str, list[dict[str, Any]]] = {}
    for abbr in sorted(grouped):
        candidates = grouped[abbr]
        block = find_abbr_block(lines, abbr)
        if block:
            existing_groups[abbr] = candidates
        else:
            new_groups[abbr] = candidates

    for abbr in sorted(existing_groups):
        _, end = find_abbr_block(lines, abbr)  # type: ignore[misc]
        insert_lines = [format_candidate(candidate) for candidate in existing_groups[abbr]]
        lines[end:end] = insert_lines

    if new_groups:
        insert_at = find_candidates_dict_end(lines)
        new_block = [f"    # {batch_note}"]
        for abbr in sorted(new_groups):
            if new_block and new_block[-1] != f"    # {batch_note}":
                new_block.append("")
            new_block.append(f'    "{abbr}": [')
            new_block.extend(format_candidate(candidate) for candidate in new_groups[abbr])
            new_block.append("    ],")
        if insert_at > 0 and lines[insert_at - 1].strip():
            new_block.insert(0, "")
        lines[insert_at:insert_at] = new_block
    elif existing_groups:
        insert_at = find_candidates_dict_end(lines)
        batch_line = f"    # {batch_note}"
        if batch_line not in lines:
            lines[insert_at:insert_at] = ["", batch_line]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Append approved fallback candidate promotions into ABBR_CANDIDATES."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--candidates-file", type=Path, default=DEFAULT_CANDIDATES_FILE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be appended without writing abbr_candidates.py.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Write a .bak copy before updating abbr_candidates.py.",
    )
    parser.add_argument(
        "--batch-note",
        default=None,
        help="Comment written before appended candidates. Defaults to current timestamp.",
    )
    args = parser.parse_args()

    source_text = args.candidates_file.read_text(encoding="utf-8")
    candidates = load_abbr_candidates(args.candidates_file)
    items = load_approved_items(args.input)
    result = plan_items(candidates, items)

    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.backup:
        backup_path = args.candidates_file.with_suffix(args.candidates_file.suffix + ".bak")
        backup_path.write_text(args.candidates_file.read_text(encoding="utf-8"), encoding="utf-8")

    batch_note = args.batch_note or (
        "Added from fallback_candidate_promotions at "
        + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    updated = apply_text_append(source_text, result["appended"], batch_note)
    args.candidates_file.write_text(updated, encoding="utf-8")
    print("==== Apply Fallback Candidate Promotions ====")
    print(f"Appended: {len(result['appended'])}")
    print(f"Skipped: {len(result['skipped'])}")
    print(f"Updated: {args.candidates_file}")


if __name__ == "__main__":
    main()
