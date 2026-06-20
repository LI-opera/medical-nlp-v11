import json
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
RESULT_PATH = CURRENT_DIR / "benchmark_results.json"
OUTPUT_PATH = CURRENT_DIR / "error_analysis_report.json"


def normalize_mapping_set(mappings: list[dict]) -> set[tuple[str, str]]:
    return {
        (
            str(item.get("abbreviation", "")).strip().upper(),
            str(item.get("expansion", "")).strip().lower()
        )
        for item in mappings
        if item.get("abbreviation") and item.get("expansion")
    }


def classify_error_type(result: dict) -> str:
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
    expected_mappings = result.get("expected_mappings", [])
    predicted_mappings = result.get("predicted_mappings", [])
    text_check = result.get("text_check", {})

    expected_set = normalize_mapping_set(expected_mappings)
    predicted_set = normalize_mapping_set(predicted_mappings)

    expected_abbrs = {abbr for abbr, _ in expected_set}
    predicted_abbrs = {abbr for abbr, _ in predicted_set}

    extra_abbrs = predicted_abbrs - expected_abbrs
    missing_abbrs = expected_abbrs - predicted_abbrs

    if extra_abbrs:
        return {
            "major_type": "Over Expansion",
            "sub_type": "Extra Abbreviation Expansion",
            "reason": "系统预测了标准答案中不存在的额外缩写扩写，通常表示低上下文误扩写或候选缺乏上下文支持。",
            "extra_abbreviations": sorted(list(extra_abbrs)),
            "missing_abbreviations": []
        }

    if missing_abbrs:
        return {
            "major_type": "Under Expansion",
            "sub_type": "Missing Abbreviation Expansion",
            "reason": "系统遗漏了标准答案中应该扩写的缩写。",
            "extra_abbreviations": [],
            "missing_abbreviations": sorted(list(missing_abbrs))
        }

    if expected_abbrs == predicted_abbrs and expected_set != predicted_set:
        return {
            "major_type": "Wrong Disambiguation",
            "sub_type": "Wrong Expansion Selection",
            "reason": "系统识别到了正确缩写，但选择了错误的扩写候选。",
            "extra_abbreviations": [],
            "missing_abbreviations": []
        }

    if text_check.get("checked") and not text_check.get("correct"):
        return {
            "major_type": "Semantic Preservation Failure",
            "sub_type": "Expanded Text Meaning Changed",
            "reason": "缩写映射正确，但扩写后的完整文本未能保持原始语义。",
            "extra_abbreviations": [],
            "missing_abbreviations": []
        }

    return {
        "major_type": "Unknown",
        "sub_type": "Needs Manual Review",
        "reason": "当前规则无法自动归因，需要人工分析。",
        "extra_abbreviations": [],
        "missing_abbreviations": []
    }


def main():
    with open(RESULT_PATH, "r", encoding="utf-8") as f:
        benchmark_data = json.load(f)

    failed_cases = [
        result for result in benchmark_data["results"]
        if not result["correct"]
    ]

    error_type_summary = {}
    taxonomy_summary = {}
    failed_case_details = []

    for result in failed_cases:
        error_type = classify_error_type(result)
        taxonomy = classify_taxonomy(result)

        error_type_summary.setdefault(error_type, 0)
        error_type_summary[error_type] += 1

        major_type = taxonomy["major_type"]
        sub_type = taxonomy["sub_type"]

        taxonomy_summary.setdefault(major_type, {})
        taxonomy_summary[major_type].setdefault(sub_type, 0)
        taxonomy_summary[major_type][sub_type] += 1

        failed_case_details.append({
            "id": result["id"],
            "category": result["category"],
            "text": result["text"],
            "expected_mappings": result["expected_mappings"],
            "predicted_mappings": result["predicted_mappings"],
            "final_expanded_text": result["final_expanded_text"],
            "system_success": result["success"],
            "mapping_correct": result["mapping_correct"],
            "text_check": result["text_check"],
            "error_type": error_type,
            "taxonomy": taxonomy
        })

    report = {
        "benchmark_summary": {
            "total_cases": benchmark_data["total"],
            "correct": benchmark_data["correct"],
            "accuracy": benchmark_data["accuracy"],
            "category_stats": benchmark_data["category_stats"]
        },
        "failed_summary": {
            "failed_count": len(failed_cases),
            "error_type_summary": error_type_summary,
            "taxonomy_summary": taxonomy_summary
        },
        "failed_cases": failed_case_details
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("==== Error Analysis Report ====")
    print(f"Total Cases: {report['benchmark_summary']['total_cases']}")
    print(f"Correct: {report['benchmark_summary']['correct']}")
    print(f"Accuracy: {report['benchmark_summary']['accuracy']:.4f}")
    print(f"Failed Count: {report['failed_summary']['failed_count']}")

    print("\nError Type Summary:")
    for error_type, count in error_type_summary.items():
        print(f"- {error_type}: {count}")

    print("\nTaxonomy Summary:")
    for major_type, sub_types in taxonomy_summary.items():
        print(f"- {major_type}")
        for sub_type, count in sub_types.items():
            print(f"  - {sub_type}: {count}")

    print(f"\nError analysis report saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()