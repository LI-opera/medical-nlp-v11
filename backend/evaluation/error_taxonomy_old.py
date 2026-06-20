#这一版现在不用了，直接在error_analysis_report中合并，错误细分了。
import json
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent

ERROR_REPORT_PATH = CURRENT_DIR / "error_analysis_report.json"
OUTPUT_PATH = CURRENT_DIR / "error_taxonomy_report.json"


def normalize_mapping_set(mappings: list[dict]) -> set[tuple[str, str]]:
    return {
        (
            str(item.get("abbreviation", "")).strip().upper(),
            str(item.get("expansion", "")).strip().lower()
        )
        for item in mappings
        if item.get("abbreviation") and item.get("expansion")
    }


def classify_taxonomy(case: dict) -> dict:
    """
    通用 Error Taxonomy V1

    不针对具体缩写写死规则，
    而是根据 expected / predicted 的结构差异进行分类。
    """

    expected_mappings = case.get("expected_mappings", [])
    predicted_mappings = case.get("predicted_mappings", [])
    text_check = case.get("text_check", {})

    expected_set = normalize_mapping_set(expected_mappings)
    predicted_set = normalize_mapping_set(predicted_mappings)

    expected_abbrs = {abbr for abbr, _ in expected_set}
    predicted_abbrs = {abbr for abbr, _ in predicted_set}

    extra_abbrs = predicted_abbrs - expected_abbrs
    missing_abbrs = expected_abbrs - predicted_abbrs

    # 1. 扩写了不该扩写的缩写
    if extra_abbrs:
        return {
            "major_type": "Over Expansion",
            "sub_type": "Extra Abbreviation Expansion",
            "reason": "系统预测了标准答案中不存在的额外缩写扩写，通常表示低上下文误扩写或候选缺乏上下文支持。",
            "extra_abbreviations": sorted(list(extra_abbrs)),
            "missing_abbreviations": []
        }

    # 2. 漏掉了应该扩写的缩写
    if missing_abbrs:
        return {
            "major_type": "Under Expansion",
            "sub_type": "Missing Abbreviation Expansion",
            "reason": "系统遗漏了标准答案中应该扩写的缩写。",
            "extra_abbreviations": [],
            "missing_abbreviations": sorted(list(missing_abbrs))
        }

    # 3. 缩写识别对了，但 expansion 错了
    if expected_abbrs == predicted_abbrs and expected_set != predicted_set:
        return {
            "major_type": "Wrong Disambiguation",
            "sub_type": "Wrong Expansion Selection",
            "reason": "系统识别到了正确缩写，但选择了错误的扩写候选。",
            "extra_abbreviations": [],
            "missing_abbreviations": []
        }

    # 4. mapping 对了，但最终文本语义检查失败
    if text_check.get("checked") and not text_check.get("correct"):
        return {
            "major_type": "Semantic Preservation Failure",
            "sub_type": "Expanded Text Meaning Changed",
            "reason": "缩写映射正确，但扩写后的完整文本未能保持原始语义，例如否定、时间或语气发生变化。",
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
    with open(ERROR_REPORT_PATH, "r", encoding="utf-8") as f:
        error_report = json.load(f)

    taxonomy_cases = []

    for error_type, cases in error_report.get("error_groups", {}).items():
        for case in cases:
            taxonomy = classify_taxonomy(case)

            taxonomy_cases.append({
                "id": case["id"],
                "category": case["category"],
                "text": case["text"],
                "expected_mappings": case["expected_mappings"],
                "predicted_mappings": case["predicted_mappings"],
                "final_expanded_text": case["final_expanded_text"],
                "error_report_type": error_type,
                "taxonomy": taxonomy
            })

    taxonomy_summary = {}

    for item in taxonomy_cases:
        major_type = item["taxonomy"]["major_type"]
        sub_type = item["taxonomy"]["sub_type"]

        taxonomy_summary.setdefault(major_type, {})
        taxonomy_summary[major_type].setdefault(sub_type, 0)
        taxonomy_summary[major_type][sub_type] += 1

    report = {
        "total_failed_cases": len(taxonomy_cases),
        "taxonomy_summary": taxonomy_summary,
        "taxonomy_cases": taxonomy_cases
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("==== Error Taxonomy Report ====")
    print(f"Total Failed Cases: {report['total_failed_cases']}")

    print("\nTaxonomy Summary:")
    for major_type, sub_types in taxonomy_summary.items():
        print(f"- {major_type}")
        for sub_type, count in sub_types.items():
            print(f"  - {sub_type}: {count}")

    print(f"\nError taxonomy report saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()