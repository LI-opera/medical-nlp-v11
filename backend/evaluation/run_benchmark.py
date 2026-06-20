import sys
import json
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))
from evaluation.abbr_benchmark_cases import ABBR_BENCHMARK_CASES
from services.abbr_service import ABBRService
def normalize_text(text:str) -> str:
    if text is None:
        return None
    #统一大小写，方便比较
    return text.strip().lower()


def compare_mappings(expected_mappings,predicted_mappings):
    #对比标准答案和系统预测结果。
    #当前v1只比较abbreviation和expansion
    expected_set = {
        (
            normalize_text(item.get("abbreviation")),
            normalize_text(item.get("expansion"))
        )
        for item in expected_mappings if item.get("abbreviation") and item.get("expansion")
    }

    predicted_set = {
        (
            normalize_text(item.get("abbreviation")),
            normalize_text(item.get("expansion"))
        )
        for item in predicted_mappings if item.get("abbreviation") and item.get("expansion")
    }
    return expected_set == predicted_set

def compare_text_contains(final_text,expected_text_contains):
    #检查最终扩写文本里是否包含指定片段
    #用于评测negation preservation这类语义保持问题
    if not expected_text_contains:
        return{
            "checked":False,
            "correct":True,
            "expected_text_contains":expected_text_contains,
            "final_text":final_text
        }
    
    if final_text is None:
        final_text = ""

    if not isinstance(final_text, str):
        final_text = str(final_text)

    final_text_norm = normalize_text(final_text)
    expected_norm = normalize_text(expected_text_contains)

    correct = expected_norm in final_text_norm
    
    return{
        "checked":True,
        "correct":correct,
        "expected_text_contains":expected_text_contains,
        "final_text":final_text
    }



def run_benchmark():
    service = ABBRService()
    total = len(ABBR_BENCHMARK_CASES)
    correct = 0
    category_stats = {}
    results = []

    for case in ABBR_BENCHMARK_CASES:
        result = None
        for _try in range(3):
            try:
                result = service.expand_verify_with_retry(
                    text=case["text"],
                    max_retries=2
                )
                break
            except Exception as e:
                if _try == 2:
                    print(f"[WARN] {case['id']} failed after retries: {e}")
                    result = {"final_result": {}, "success": False, "error": str(e)}
                else:
                    time.sleep(3)
        
        final_result = result.get("final_result",{})
        predicted_mappings = final_result.get("mappings",[])
        final_expanded_text = (
            final_result.get("expanded_text","")
        )

        is_correct = compare_mappings(
            expected_mappings=case["expected_mappings"],
            predicted_mappings=predicted_mappings
        )
        text_check = compare_text_contains(
            final_text=final_expanded_text,
            expected_text_contains=case.get("expected_text_contains")
        )
        final_correct = is_correct and text_check["correct"]

        if final_correct:
            correct += 1

        category = case["category"]
        if category not in category_stats:
            category_stats[category] = {
                "total":0,
                "correct":0
            }
        category_stats[category]["total"] += 1

        if final_correct:
            category_stats[category]["correct"] += 1
        
        results.append({
            "id": case["id"],
            "category": case["category"],
            "text": case["text"],
            "success": result.get("success"),
            "expected_mappings": case["expected_mappings"],
            "predicted_mappings": predicted_mappings,
            "final_expanded_text": final_expanded_text,
            "mapping_correct": is_correct,
            "text_check": text_check,
            "correct": final_correct
        })

    accuracy = correct / total if total >0 else 0

    print("==== Benchmark Result ====")
    print(f"Total Cases:{total}")
    print(f"Correct:{correct}")
    print(f"Expansion Accuracy:{accuracy:.4f}")

    print("\n ==== Category Results ====")
    for category,stats in category_stats.items():
        category_accuracy = stats["correct"] / stats["total"] if stats["total"] >0 else 0
        print(
            f"{category}:"
            f"{stats['correct']}/{stats['total']}  "
            f"Accuracy = {category_accuracy:.4f}"
        )

    print("\n === Failed Cases ===")
    for result in results:
        if not result["correct"]:
            print(f'- {result["id"]} | {result["category"]}')
            print(f'  Text: {result["text"]}')
            print(f'  System Success: {result.get("success")}')
            print(f'  Expected: {result["expected_mappings"]}')
            print(f'  Predicted: {result["predicted_mappings"]}')
            print(f'  Final Text: {result.get("final_expanded_text")}')
            print(f'  Mapping Correct: {result.get("mapping_correct")}')
            print(f'  Text Check: {result.get("text_check")}')
    output_path = BACKEND_DIR / "evaluation" / "benchmark_results.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total": total,
                "correct": correct,
                "accuracy": accuracy,
                "category_stats": category_stats,
                "results": results
            },
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"\nBenchmark results saved to: {output_path}")

if __name__ == "__main__":
    run_benchmark()
