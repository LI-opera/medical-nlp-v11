import sys
import json
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))
from evaluation.abbr_benchmark_cases import ABBR_BENCHMARK_CASES
from services.abbr_service import ABBRService
from evaluation.concept_match import compare_mappings_snomed
from utils.structured_logger import exc_meta, log_benchmark, text_meta
from utils.trace_context import get_job_id, new_job_id, new_request_id, trace_context
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



def run_benchmark(cases=None, output_path=None, progress_callback=None):
    job_id = get_job_id() or new_job_id("bench")
    job_start = time.perf_counter()
    service = ABBRService()
    benchmark_cases = cases or ABBR_BENCHMARK_CASES
    total = len(benchmark_cases)
    correct = 0
    category_stats = {}
    results = []
    log_benchmark(
        "benchmark.job.start",
        component="run_benchmark",
        job_id=job_id,
        total=total,
        output_path=str(output_path or BACKEND_DIR / "evaluation" / "benchmark_results.json"),
        ok=True,
    )

    for index, case in enumerate(benchmark_cases, start=1):
        # benchmark 的统计单位是 case。一句话内部的多个 record 只用于诊断，
        # 但该句只计一次正确或错误，不按 record 数重复计算 accuracy。
        case_start = time.perf_counter()
        case_request_id = new_request_id("bench_case")
        log_benchmark(
            "benchmark.case.start",
            component="run_benchmark",
            job_id=job_id,
            request_id=case_request_id,
            case_id=case.get("id"),
            category=case.get("category"),
            current=index,
            total=total,
            ok=True,
            **text_meta(case.get("text")),
        )
        if progress_callback:
            progress_callback({
                "current": index,
                "total": total,
                "case_id": case.get("id"),
                "category": case.get("category"),
                "text": case.get("text"),
            })

        result = None
        for _try in range(3):
            try:
                with trace_context(request_id=case_request_id, job_id=job_id, case_id=case.get("id")):
                    result = service.expand_verify_with_retry(
                        text=case["text"],
                        max_retries=2
                    )
                break
            except Exception as e:
                if _try == 2:
                    print(f"[WARN] {case['id']} failed after retries: {e}")
                    log_benchmark(
                        "benchmark.case.error",
                        component="run_benchmark",
                        job_id=job_id,
                        request_id=case_request_id,
                        case_id=case.get("id"),
                        category=case.get("category"),
                        try_count=_try + 1,
                        duration_ms=round((time.perf_counter() - case_start) * 1000, 2),
                        ok=False,
                        level="ERROR",
                        **exc_meta(e),
                    )
                    result = {"final_result": {}, "success": False, "error": str(e)}
                else:
                    time.sleep(3)
        
        final_result = result.get("final_result",{})
        predicted_mappings = final_result.get("mappings",[])
        mapping_states = final_result.get("mapping_states", []) or []
        mapping_standardizations = final_result.get("mapping_standardizations", []) or []
        success_breakdown = result.get("success_breakdown") or final_result.get("success_breakdown") or {}
        compact_standardizations = [
            {
                "abbreviation": item.get("abbreviation"),
                "expansion": item.get("expansion"),
                "chosen_concept": item.get("chosen_concept"),
                "candidate_count": len(item.get("candidates") or []),
                "top_candidates": (item.get("candidates") or [])[:3],
            }
            for item in mapping_standardizations
        ]
        final_expanded_text = (
            final_result.get("expanded_text","")
        )

        is_correct = compare_mappings_snomed(
            service,
            case["expected_mappings"],
            predicted_mappings
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
        log_benchmark(
            "benchmark.case.end",
            component="run_benchmark",
            job_id=job_id,
            request_id=case_request_id,
            case_id=case.get("id"),
            category=case.get("category"),
            current=index,
            total=total,
            correct=final_correct,
            mapping_correct=is_correct,
            text_check_correct=text_check["correct"],
            success=result.get("success"),
            expansion_success=result.get("expansion_success"),
            standardization_success=result.get("standardization_success"),
            duration_ms=round((time.perf_counter() - case_start) * 1000, 2),
            ok=True,
        )
        
        results.append({
            "id": case["id"],
            "category": case["category"],
            "text": case["text"],
            "success": result.get("success"),
            "expansion_success": result.get("expansion_success"),
            "standardization_success": result.get("standardization_success"),
            "success_breakdown": success_breakdown,
            "expected_mappings": case["expected_mappings"],
            "predicted_mappings": predicted_mappings,
            "mapping_states": mapping_states,
            "mapping_standardizations": compact_standardizations,
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
    output_path = output_path or BACKEND_DIR / "evaluation" / "benchmark_results.json"

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
    log_benchmark(
        "benchmark.job.end",
        component="run_benchmark",
        job_id=job_id,
        total=total,
        correct=correct,
        accuracy=accuracy,
        output_path=str(output_path),
        duration_ms=round((time.perf_counter() - job_start) * 1000, 2),
        ok=True,
    )

if __name__ == "__main__":
    run_benchmark()
