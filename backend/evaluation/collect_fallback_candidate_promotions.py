import argparse
import json
import sys
from pathlib import Path
from typing import Any


CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent
DEFAULT_INPUT = CURRENT_DIR / "benchmark_results.json"
DEFAULT_JSON_OUTPUT = CURRENT_DIR / "fallback_candidate_promotions.json"
DEFAULT_MD_OUTPUT = CURRENT_DIR / "fallback_candidate_promotions.md"

sys.path.append(str(BACKEND_DIR))
from data.abbr_candidates import ABBR_CANDIDATES  # noqa: E402


def norm_abbr(value: Any) -> str:
    return str(value or "").strip().upper()


def norm_expansion(value: Any) -> str:
    return str(value or "").strip().lower()


def existing_candidate_keys() -> set[tuple[str, str]]:
    keys = set()
    for abbr, candidates in ABBR_CANDIDATES.items():
        for candidate in candidates or []:
            keys.add((norm_abbr(abbr), norm_expansion(candidate.get("expansion"))))
    return keys


def standardization_lookup(result: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    lookup = {}
    for item in result.get("mapping_standardizations", []) or []:
        key = (norm_abbr(item.get("abbreviation")), norm_expansion(item.get("expansion")))
        lookup[key] = item
    return lookup


def concept_brief(concept: dict[str, Any]) -> dict[str, Any]:
    return {
        "concept_id": concept.get("concept_id"),
        "concept_name": concept.get("concept_name"),
        "domain_id": concept.get("domain_id"),
        "concept_code": concept.get("concept_code"),
    }


def collect_items(benchmark_data: dict[str, Any]) -> list[dict[str, Any]]:
    existing = existing_candidate_keys()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for result in benchmark_data.get("results", []) or []:
        if result.get("correct") is not True:
            continue

        standardizations = standardization_lookup(result)
        for state in result.get("mapping_states", []) or []:
            abbr = norm_abbr(state.get("abbreviation"))
            expansion = str(state.get("expansion") or "").strip()
            key = (abbr, norm_expansion(expansion))

            if not abbr or not expansion:
                continue
            if state.get("source") != "fallback":
                continue
            if state.get("status") != "CODED":
                continue

            std_item = standardizations.get(key) or {}
            chosen_concept = std_item.get("chosen_concept")
            if not chosen_concept:
                continue

            domain = (
                state.get("domain")
                or state.get("label")
                or chosen_concept.get("domain_id")
                or "Unknown"
            )
            item = grouped.setdefault(
                key,
                {
                    "abbreviation": abbr,
                    "expansion": expansion,
                    "domain": domain,
                    "already_exists": key in existing,
                    "support_count": 0,
                    "case_ids": [],
                    "examples": [],
                    "chosen_concepts": [],
                    "candidate_to_append": {
                        "expansion": expansion,
                        "domain": domain,
                    },
                },
            )
            item["support_count"] += 1
            item["case_ids"].append(result.get("id"))
            item["examples"].append(
                {
                    "id": result.get("id"),
                    "category": result.get("category"),
                    "text": result.get("text"),
                    "final_expanded_text": result.get("final_expanded_text"),
                }
            )

            brief = concept_brief(chosen_concept)
            if brief not in item["chosen_concepts"]:
                item["chosen_concepts"].append(brief)

    return sorted(
        grouped.values(),
        key=lambda item: (
            item["already_exists"],
            -item["support_count"],
            item["abbreviation"],
            item["expansion"].lower(),
        ),
    )


def build_report(benchmark_data: dict[str, Any], source_file: Path) -> dict[str, Any]:
    items = collect_items(benchmark_data)
    new_items = [item for item in items if not item["already_exists"]]
    existing_items = [item for item in items if item["already_exists"]]
    return {
        "source_result_file": str(source_file),
        "selection_rule": (
            "case.correct is true AND mapping_state.source == 'fallback' "
            "AND mapping_state.status == 'CODED' AND chosen_concept exists"
        ),
        "total_items": len(items),
        "new_item_count": len(new_items),
        "already_exists_count": len(existing_items),
        "items": items,
        "new_items": new_items,
        "already_exists_items": existing_items,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# fallback 成功候选沉淀清单",
        "",
        "## 筛选口径",
        "",
        "- case 必须是 benchmark 正确案例：`correct = true`。",
        "- record 必须来自 fallback：`source = fallback`。",
        "- record 必须已经成功标准化：`status = CODED`。",
        "- 同一 abbreviation + expansion 必须存在 `chosen_concept`。",
        "- 本文件只展示候选，不写入 primary 候选库。",
        "",
        "## 汇总",
        "",
        f"- 候选总数: `{report['total_items']}`",
        f"- 新候选数: `{report['new_item_count']}`",
        f"- primary 中已存在: `{report['already_exists_count']}`",
        "",
        "## 新候选",
        "",
    ]

    if not report["new_items"]:
        lines.extend(["- 本轮没有新的 fallback 成功候选。", ""])
    else:
        for item in report["new_items"]:
            lines.extend(render_item(item))

    lines.extend(["## 已存在候选", ""])
    if not report["already_exists_items"]:
        lines.extend(["- 无。", ""])
    else:
        for item in report["already_exists_items"]:
            lines.append(
                f"- `{item['abbreviation']}` -> `{item['expansion']}` "
                f"({item['domain']}), support_count={item['support_count']}"
            )
        lines.append("")

    return "\n".join(lines)


def render_item(item: dict[str, Any]) -> list[str]:
    return [
        f"### {item['abbreviation']} -> {item['expansion']}",
        "",
        f"- domain: `{item['domain']}`",
        f"- support_count: `{item['support_count']}`",
        f"- case_ids: `{json.dumps(item['case_ids'], ensure_ascii=False)}`",
        f"- chosen_concepts: `{json.dumps(item['chosen_concepts'], ensure_ascii=False)}`",
        f"- candidate_to_append: `{json.dumps(item['candidate_to_append'], ensure_ascii=False)}`",
        "",
        "示例：",
        "",
        "```json",
        json.dumps(item["examples"][:3], ensure_ascii=False, indent=2),
        "```",
        "",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect fallback-generated candidates that were successfully coded."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--md-output", type=Path, default=DEFAULT_MD_OUTPUT)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        benchmark_data = json.load(f)

    report = build_report(benchmark_data, args.input)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.md_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.md_output.write_text(render_markdown(report), encoding="utf-8")

    print("==== Fallback Candidate Promotions ====")
    print(f"Total items: {report['total_items']}")
    print(f"New items: {report['new_item_count']}")
    print(f"Already exists: {report['already_exists_count']}")
    print(f"JSON saved to: {args.json_output}")
    print(f"Markdown saved to: {args.md_output}")


if __name__ == "__main__":
    main()
