import json
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
sys.path.append(str(CURRENT_DIR.parent))
from evaluation.paths import (
    BENCHMARK_RESULTS_PATH,
    ERROR_ANALYSIS_REPORT_PATH,
    ensure_archive_dir,
)

RESULT_PATH = BENCHMARK_RESULTS_PATH
OUTPUT_PATH = ERROR_ANALYSIS_REPORT_PATH


def normalize_mapping_set(mappings: list[dict]) -> set[tuple[str, str]]:
    return {
        (
            str(item.get("abbreviation", "")).strip().upper(),
            str(item.get("expansion", "")).strip().lower(),
        )
        for item in mappings
        if item.get("abbreviation") and item.get("expansion")
    }


def classify_error_type(result: dict) -> str:
    # 这些标签描述 case 级别的失败维度；record 状态会单独统计，不能直接
    # 加到 case 数量中，否则会把一句话里的多个实体重复计数。
    category = result.get("category")
    if category == "low_context_abbreviation":
        return "low_context_over_expansion"

    expected = result.get("expected_mappings", [])
    predicted = result.get("predicted_mappings", [])

    if expected and predicted:
        return "wrong_expansion"
    if expected and not predicted:
        return "missing_expansion"
    if not expected and predicted:
        return "over_expansion"
    return "unknown_error"


def classify_taxonomy(result: dict) -> dict:
    expected = normalize_mapping_set(result.get("expected_mappings", []))
    predicted = normalize_mapping_set(result.get("predicted_mappings", []))
    text_check = result.get("text_check", {})

    expected_abbrs = {abbr for abbr, _ in expected}
    predicted_abbrs = {abbr for abbr, _ in predicted}
    extra_abbrs = sorted(predicted_abbrs - expected_abbrs)
    missing_abbrs = sorted(expected_abbrs - predicted_abbrs)

    if extra_abbrs:
        return {
            "major_type": "Over Expansion",
            "sub_type": "Extra Abbreviation Expansion",
            "reason": "The system expanded abbreviations that are not present in the gold mappings.",
            "extra_abbreviations": extra_abbrs,
            "missing_abbreviations": [],
        }

    if missing_abbrs:
        return {
            "major_type": "Under Expansion",
            "sub_type": "Missing Abbreviation Expansion",
            "reason": "The system missed abbreviations that are present in the gold mappings.",
            "extra_abbreviations": [],
            "missing_abbreviations": missing_abbrs,
        }

    if expected_abbrs == predicted_abbrs and expected != predicted:
        return {
            "major_type": "Wrong Disambiguation",
            "sub_type": "Wrong Expansion Selection",
            "reason": "The system found the expected abbreviation but selected a different expansion.",
            "extra_abbreviations": [],
            "missing_abbreviations": [],
        }

    if text_check.get("checked") and not text_check.get("correct"):
        return {
            "major_type": "Semantic Preservation Failure",
            "sub_type": "Expanded Text Meaning Changed",
            "reason": "The mapping is correct, but the expanded text failed the semantic preservation check.",
            "extra_abbreviations": [],
            "missing_abbreviations": [],
        }

    return {
        "major_type": "Unknown",
        "sub_type": "Needs Manual Review",
        "reason": "The current deterministic rules cannot classify this failure.",
        "extra_abbreviations": [],
        "missing_abbreviations": [],
    }


def build_mapping_delta(result: dict) -> dict:
    expected = normalize_mapping_set(result.get("expected_mappings", []))
    predicted = normalize_mapping_set(result.get("predicted_mappings", []))
    expected_by_abbr = {abbr: expansion for abbr, expansion in expected}
    predicted_by_abbr = {abbr: expansion for abbr, expansion in predicted}

    wrong_expansions = []
    for abbr in sorted(set(expected_by_abbr) & set(predicted_by_abbr)):
        if expected_by_abbr[abbr] != predicted_by_abbr[abbr]:
            wrong_expansions.append(
                {
                    "abbreviation": abbr,
                    "expected": expected_by_abbr[abbr],
                    "predicted": predicted_by_abbr[abbr],
                }
            )

    return {
        "extra_abbreviations": sorted(set(predicted_by_abbr) - set(expected_by_abbr)),
        "missing_abbreviations": sorted(set(expected_by_abbr) - set(predicted_by_abbr)),
        "wrong_expansions": wrong_expansions,
    }


def summarize_record_statuses(results: list[dict]) -> dict:
    summary = {}
    for result in results:
        for record in result.get("mapping_states", []) or []:
            status = record.get("status") or "UNKNOWN"
            summary[status] = summary.get(status, 0) + 1
    return summary


def summarize_failure_stages(results: list[dict]) -> dict:
    summary = {}
    for result in results:
        for record in result.get("mapping_states", []) or []:
            failure = record.get("failure") or {}
            stage = failure.get("stage")
            if stage:
                summary[stage] = summary.get(stage, 0) + 1
    return summary


def summarize_candidate_sources(results: list[dict]) -> dict:
    summary = {}
    for result in results:
        items = result.get("mapping_states", []) or result.get("predicted_mappings", []) or []
        for item in items:
            source = item.get("source") or "unknown"
            summary[source] = summary.get(source, 0) + 1
    return summary


def summarize_not_expanded_failure_types(results: list[dict]) -> dict:
    summary = {}
    for result in results:
        for record in result.get("mapping_states", []) or []:
            if record.get("status") != "NOT_EXPANDED":
                continue
            failure_type = (record.get("failure") or {}).get("type") or "UNKNOWN"
            summary[failure_type] = summary.get(failure_type, 0) + 1
    return summary


def summarize_not_expanded_failure_subtypes(results: list[dict]) -> dict:
    summary = {}
    for result in results:
        for record in result.get("mapping_states", []) or []:
            if record.get("status") != "NOT_EXPANDED":
                continue
            failure_subtype = (record.get("failure") or {}).get("subtype")
            if not failure_subtype:
                continue
            summary[failure_subtype] = summary.get(failure_subtype, 0) + 1
    return summary


def summarize_coverage_issues(results: list[dict]) -> dict:
    summary = {}
    for result in results:
        for record in result.get("mapping_states", []) or []:
            coverage = record.get("coverage") or {}
            failure = record.get("failure") or {}
            evidence = failure.get("evidence") or {}
            issues = coverage.get("issues") or evidence.get("coverage_issues") or []
            for issue in issues:
                summary[issue] = summary.get(issue, 0) + 1
    return summary


def summarize_suggestions(results: list[dict]) -> dict:
    summary = {}
    for result in results:
        for record in result.get("mapping_states", []) or []:
            suggestion = (record.get("failure") or {}).get("suggestion")
            if suggestion:
                summary[suggestion] = summary.get(suggestion, 0) + 1
    return summary


def summarize_case_categories(cases: list[dict]) -> dict:
    summary = {}
    for case in cases:
        category = case.get("category") or "unknown"
        summary[category] = summary.get(category, 0) + 1
    return summary


def is_benchmark_mismatch(result: dict) -> bool:
    return result.get("correct") is False


def is_expansion_blocked(result: dict) -> bool:
    if result.get("expansion_success") is False:
        return True
    return any(
        record.get("status") in ("NOT_EXPANDED", "ABSTAIN", "PENDING")
        for record in result.get("mapping_states", []) or []
    )


def is_standardization_failure(result: dict) -> bool:
    if result.get("standardization_success") is False:
        return True
    return any(
        record.get("status") == "WITHHELD"
        for record in result.get("mapping_states", []) or []
    )


def build_failure_reasons(result: dict, labels: dict) -> list[str]:
    reasons = []
    delta = build_mapping_delta(result)

    if labels["benchmark_mismatch"]:
        if delta["extra_abbreviations"]:
            reasons.append("target_selection_error")
        if delta["missing_abbreviations"]:
            reasons.append("missing_expected_mapping")
        if delta["wrong_expansions"]:
            reasons.append("wrong_expansion_selection")
        if not reasons:
            reasons.append("benchmark_gold_mismatch")

    if labels["expansion_blocked"]:
        reasons.append("no_expansion_cannot_standardize")

    if labels["standardization_failure"]:
        if labels["expansion_blocked"]:
            reasons.append("standardization_blocked_by_expansion")
        if any(
            record.get("status") == "WITHHELD"
            for record in result.get("mapping_states", []) or []
        ):
            reasons.append("expansion_exists_but_withheld")

    return list(dict.fromkeys(reasons))


def build_case_detail(result: dict, issue_type: str | None = None) -> dict:
    detail = {
        "id": result["id"],
        "category": result["category"],
        "text": result["text"],
        "expected_mappings": result["expected_mappings"],
        "predicted_mappings": result["predicted_mappings"],
        "mapping_delta": build_mapping_delta(result),
        "mapping_states": result.get("mapping_states", []),
        "mapping_standardizations": result.get("mapping_standardizations", []),
        "final_expanded_text": result["final_expanded_text"],
        "system_success": result["success"],
        "expansion_success": result.get("expansion_success"),
        "standardization_success": result.get("standardization_success"),
        "success_breakdown": result.get("success_breakdown", {}),
        "mapping_correct": result["mapping_correct"],
        "benchmark_correct": result["correct"],
        "text_check": result["text_check"],
    }
    if issue_type:
        detail["issue_type"] = issue_type
    return detail


def build_overall_failure_case(result: dict) -> dict:
    labels = {
        "benchmark_mismatch": is_benchmark_mismatch(result),
        "expansion_blocked": is_expansion_blocked(result),
        "standardization_failure": is_standardization_failure(result),
    }
    detail = build_case_detail(result, issue_type="overall_failure")
    detail["labels"] = labels
    detail["failure_reasons"] = build_failure_reasons(result, labels)
    detail["error_type"] = classify_error_type(result) if labels["benchmark_mismatch"] else None
    detail["taxonomy"] = classify_taxonomy(result) if labels["benchmark_mismatch"] else None
    return detail


def build_overall_failure_analysis(all_results: list[dict]) -> dict:
    total = len(all_results)
    benchmark_cases = [r for r in all_results if is_benchmark_mismatch(r)]
    expansion_cases = [r for r in all_results if is_expansion_blocked(r)]
    standardization_cases = [r for r in all_results if is_standardization_failure(r)]

    benchmark_ids = {r["id"] for r in benchmark_cases}
    expansion_ids = {r["id"] for r in expansion_cases}
    standardization_ids = {r["id"] for r in standardization_cases}
    failure_ids = benchmark_ids | expansion_ids | standardization_ids
    success_ids = {r["id"] for r in all_results} - failure_ids

    failure_cases = [
        build_overall_failure_case(result)
        for result in all_results
        if result["id"] in failure_ids
    ]

    return {
        "total_cases": total,
        "overall_success_count": len(success_ids),
        "overall_failure_count": len(failure_ids),
        "overall_success_rate": (len(success_ids) / total if total else 0),
        "success_definition": {
            "benchmark_correct": True,
            "expansion_success": True,
            "standardization_success": True,
        },
        "failure_definition": (
            "benchmark_mismatch OR expansion_blocked OR standardization_failure"
        ),
        "failure_label_summary": {
            "benchmark_mismatch": len(benchmark_ids),
            "expansion_blocked": len(expansion_ids),
            "standardization_failure": len(standardization_ids),
        },
        "failure_set_relationship": {
            "labels_are_overlapping": True,
            "labels_should_not_be_summed": True,
            "benchmark_mismatch_only_count": len(
                benchmark_ids - expansion_ids - standardization_ids
            ),
            "benchmark_mismatch_and_standardization_failure_count": len(
                benchmark_ids & standardization_ids
            ),
            "benchmark_mismatch_and_expansion_blocked_count": len(
                benchmark_ids & expansion_ids
            ),
            "expansion_blocked_is_subset_of_standardization_failure": (
                expansion_ids <= standardization_ids
            ),
            "overall_failure_case_ids": sorted(failure_ids),
            "overall_success_case_ids": sorted(success_ids),
            "benchmark_mismatch_case_ids": sorted(benchmark_ids),
            "expansion_blocked_case_ids": sorted(expansion_ids),
            "standardization_failure_case_ids": sorted(standardization_ids),
        },
        "failure_category_summary": summarize_case_categories(failure_cases),
        "failure_cases": failure_cases,
    }


def build_legacy_business_diagnostics(all_results: list[dict]) -> dict:
    business_non_success_cases = [
        build_case_detail(result, issue_type="business_non_success")
        for result in all_results
        if not result.get("success")
    ]
    expansion_failure_cases = [
        build_case_detail(result, issue_type="expansion_failure")
        for result in all_results
        if is_expansion_blocked(result)
    ]
    standardization_failure_cases = [
        build_case_detail(result, issue_type="standardization_failure")
        for result in all_results
        if is_standardization_failure(result)
    ]

    return {
        "business_non_success_count": len(business_non_success_cases),
        "expansion_failure_count": len(expansion_failure_cases),
        "standardization_failure_count": len(standardization_failure_cases),
        "business_non_success_category_summary": summarize_case_categories(
            business_non_success_cases
        ),
        "expansion_failure_category_summary": summarize_case_categories(
            expansion_failure_cases
        ),
        "standardization_failure_category_summary": summarize_case_categories(
            standardization_failure_cases
        ),
        "business_non_success_cases": business_non_success_cases,
        "expansion_failure_cases": expansion_failure_cases,
        "standardization_failure_cases": standardization_failure_cases,
    }


def main():
    ensure_archive_dir()
    with open(RESULT_PATH, "r", encoding="utf-8") as f:
        benchmark_data = json.load(f)

    all_results = benchmark_data["results"]
    failed_cases = [result for result in all_results if not result["correct"]]
    business_success_count = sum(1 for result in all_results if result.get("success"))
    expansion_success_count = sum(1 for result in all_results if result.get("expansion_success"))
    standardization_success_count = sum(
        1 for result in all_results if result.get("standardization_success")
    )

    error_type_summary = {}
    taxonomy_summary = {}
    failed_case_details = []

    for result in failed_cases:
        error_type = classify_error_type(result)
        taxonomy = classify_taxonomy(result)
        error_type_summary[error_type] = error_type_summary.get(error_type, 0) + 1
        taxonomy_summary.setdefault(taxonomy["major_type"], {})
        taxonomy_summary[taxonomy["major_type"]][taxonomy["sub_type"]] = (
            taxonomy_summary[taxonomy["major_type"]].get(taxonomy["sub_type"], 0) + 1
        )
        detail = build_case_detail(result, issue_type="benchmark_failed")
        detail["error_type"] = error_type
        detail["taxonomy"] = taxonomy
        failed_case_details.append(detail)

    overall_failure_analysis = build_overall_failure_analysis(all_results)

    report = {
        "benchmark_summary": {
            "total_cases": benchmark_data["total"],
            "correct": benchmark_data["correct"],
            "accuracy": benchmark_data["accuracy"],
            "business_success_count": benchmark_data.get(
                "business_success_count", business_success_count
            ),
            "expansion_success_count": benchmark_data.get(
                "expansion_success_count", expansion_success_count
            ),
            "standardization_success_count": benchmark_data.get(
                "standardization_success_count", standardization_success_count
            ),
            "category_stats": benchmark_data["category_stats"],
        },
        "overall_failure_analysis": overall_failure_analysis,
        "failed_summary": {
            "failed_count": len(failed_cases),
            "error_type_summary": error_type_summary,
            "taxonomy_summary": taxonomy_summary,
            "record_status_summary": summarize_record_statuses(failed_cases),
            "failure_stage_summary": summarize_failure_stages(failed_cases),
            "candidate_source_summary": summarize_candidate_sources(failed_cases),
            "not_expanded_failure_type_summary": summarize_not_expanded_failure_types(
                failed_cases
            ),
            "not_expanded_failure_subtype_summary": summarize_not_expanded_failure_subtypes(
                failed_cases
            ),
            "coverage_issue_summary": summarize_coverage_issues(failed_cases),
            "suggestion_summary": summarize_suggestions(failed_cases),
        },
        "diagnostic_summary": {
            "record_status_summary": summarize_record_statuses(all_results),
            "failure_stage_summary": summarize_failure_stages(all_results),
            "candidate_source_summary": summarize_candidate_sources(all_results),
            "not_expanded_failure_type_summary": summarize_not_expanded_failure_types(
                all_results
            ),
            "not_expanded_failure_subtype_summary": summarize_not_expanded_failure_subtypes(
                all_results
            ),
            "coverage_issue_summary": summarize_coverage_issues(all_results),
            "suggestion_summary": summarize_suggestions(all_results),
        },
        "business_diagnostic_cases": build_legacy_business_diagnostics(all_results),
        "failed_cases": failed_case_details,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("==== Error Analysis Report ====")
    print(f"Total Cases: {report['benchmark_summary']['total_cases']}")
    print(f"Benchmark Correct: {report['benchmark_summary']['correct']}")
    print(f"Benchmark Accuracy: {report['benchmark_summary']['accuracy']:.4f}")
    print(
        "Overall Success: "
        f"{overall_failure_analysis['overall_success_count']}/"
        f"{overall_failure_analysis['total_cases']} = "
        f"{overall_failure_analysis['overall_success_rate']:.4f}"
    )
    print(f"Overall Failure: {overall_failure_analysis['overall_failure_count']}")
    print("Failure Label Summary:")
    for label, count in overall_failure_analysis["failure_label_summary"].items():
        print(f"- {label}: {count}")
    print(f"\nError analysis report saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
