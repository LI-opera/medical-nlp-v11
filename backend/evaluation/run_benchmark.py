"""运行缩写标准化 benchmark，并生成统一结果文件。"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from evaluation.concept_match import compare_mappings_snomed
from evaluation.paths import (
    BENCHMARK_CASES_PATH,
    BENCHMARK_RESULTS_PATH,
    ensure_archive_dir,
)
from services.abbr_service import ABBRService
from utils.structured_logger import exc_meta, log_benchmark, text_meta
from utils.trace_context import get_job_id, new_job_id, new_request_id, trace_context


# 并行 worker 内部各自持有 ABBRService，避免模型、Embedding 和 Milvus client
# 在多个线程之间共享。代价是每个 worker 可能加载一份模型，因此不要盲目调大。
_thread_local = threading.local()


def normalize_text(text: str | None) -> str:
    if text is None:
        return ""
    return str(text).strip().lower()


def load_default_benchmark_cases(path: Path = BENCHMARK_CASES_PATH) -> list[dict]:
    """读取 examples/benchmarks 下统一格式的默认 benchmark。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise ValueError(f"Benchmark file must contain cases: list: {path}")
    return cases


def compare_text_contains(final_text: str | None, expected_text_contains: str | None) -> dict:
    """检查扩写文本是否保留 benchmark 指定的语义片段。"""
    if not expected_text_contains:
        return {
            "checked": False,
            "correct": True,
            "expected_text_contains": expected_text_contains,
            "final_text": final_text,
        }

    final_text = "" if final_text is None else str(final_text)
    correct = normalize_text(expected_text_contains) in normalize_text(final_text)
    return {
        "checked": True,
        "correct": correct,
        "expected_text_contains": expected_text_contains,
        "final_text": final_text,
    }


def _get_thread_service() -> ABBRService:
    """为当前 worker 创建并缓存独立的 ABBRService。"""
    service = getattr(_thread_local, "service", None)
    if service is None:
        service = ABBRService()
        _thread_local.service = service
    return service


def _compact_standardizations(items: list[dict]) -> list[dict]:
    return [
        {
            "abbreviation": item.get("abbreviation"),
            "expansion": item.get("expansion"),
            "chosen_concept": item.get("chosen_concept"),
            "candidate_count": len(item.get("candidates") or []),
            "top_candidates": (item.get("candidates") or [])[:3],
        }
        for item in items
    ]


def _run_one_case(case: dict, job_id: str, total: int) -> dict:
    """执行一个 case；串行和并行模式共用这段判定与输出逻辑。"""
    service = _get_thread_service()
    case_start = time.perf_counter()
    request_id = new_request_id("bench_case")
    index = case.get("_benchmark_index", 0)
    log_benchmark(
        "benchmark.case.start",
        component="run_benchmark",
        job_id=job_id,
        request_id=request_id,
        case_id=case.get("id"),
        category=case.get("category"),
        current=index,
        total=total,
        ok=True,
        **text_meta(case.get("text")),
    )

    result = None
    for attempt in range(3):
        try:
            with trace_context(
                request_id=request_id,
                job_id=job_id,
                case_id=case.get("id"),
            ):
                result = service.expand_verify_with_retry(
                    text=case["text"],
                    max_retries=2,
                )
            break
        except Exception as exc:
            if attempt == 2:
                log_benchmark(
                    "benchmark.case.error",
                    component="run_benchmark",
                    job_id=job_id,
                    request_id=request_id,
                    case_id=case.get("id"),
                    category=case.get("category"),
                    try_count=attempt + 1,
                    duration_ms=round((time.perf_counter() - case_start) * 1000, 2),
                    ok=False,
                    level="ERROR",
                    **exc_meta(exc),
                )
                result = {
                    "final_result": {},
                    "success": False,
                    "error": str(exc),
                }
            else:
                time.sleep(3)

    final_result = result.get("final_result", {}) or {}
    predicted_mappings = final_result.get("mappings", [])
    mapping_states = final_result.get("mapping_states", []) or []
    mapping_standardizations = final_result.get("mapping_standardizations", []) or []
    success_breakdown = (
        result.get("success_breakdown")
        or final_result.get("success_breakdown")
        or {}
    )
    final_expanded_text = final_result.get("expanded_text", "")

    is_correct = compare_mappings_snomed(
        service,
        case["expected_mappings"],
        predicted_mappings,
    )
    text_check = compare_text_contains(
        final_expanded_text,
        case.get("expected_text_contains"),
    )
    final_correct = is_correct and text_check["correct"]

    log_benchmark(
        "benchmark.case.end",
        component="run_benchmark",
        job_id=job_id,
        request_id=request_id,
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

    return {
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
        "mapping_standardizations": _compact_standardizations(mapping_standardizations),
        "final_expanded_text": final_expanded_text,
        "mapping_correct": is_correct,
        "text_check": text_check,
        "correct": final_correct,
    }


def _progress_event(result: dict, current: int, total: int) -> dict:
    return {
        "current": current,
        "total": total,
        "case_id": result.get("id"),
        "category": result.get("category"),
        "text": result.get("text"),
    }


def _build_category_stats(results: list[dict]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for result in results:
        category = result["category"]
        bucket = stats.setdefault(category, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if result["correct"]:
            bucket["correct"] += 1
    return stats


def _print_failed_cases(results: list[dict]) -> None:
    print("\n=== Failed Cases ===")
    for result in results:
        if result["correct"]:
            continue
        print(f'- {result["id"]} | {result["category"]}')
        print(f'  Text: {result["text"]}')
        print(f'  System Success: {result.get("success")}')
        print(f'  Expected: {result["expected_mappings"]}')
        print(f'  Predicted: {result["predicted_mappings"]}')
        print(f'  Final Text: {result.get("final_expanded_text")}')
        print(f'  Mapping Correct: {result.get("mapping_correct")}')
        print(f'  Text Check: {result.get("text_check")}')


def run_benchmark(
    cases: list[dict] | None = None,
    output_path: Path | None = None,
    progress_callback: Callable[[dict], None] | None = None,
    workers: int | None = None,
) -> dict:
    """运行 benchmark。

    调试方式：
    - 网页上传调用不传 `workers`，默认使用串行模式，保持进度和资源占用稳定。
    - 手动并行：`BENCH_WORKERS=2 python backend/evaluation/run_benchmark.py`。
    - 代码调用也可以直接传 `workers=2` 或 `workers=4`。
    - worker 数建议从 2 开始，过高可能触发 LLM 限流或重复加载模型导致内存不足。
    """
    job_id = get_job_id() or new_job_id("bench")
    job_start = time.perf_counter()
    benchmark_cases = cases if cases is not None else load_default_benchmark_cases()
    total = len(benchmark_cases)
    workers = workers or int(os.getenv("BENCH_WORKERS", "1"))
    workers = max(1, workers)
    output_path = output_path or BENCHMARK_RESULTS_PATH
    ensure_archive_dir()

    # 给内部任务附加顺序编号，但不写入最终 JSON，保证并行完成顺序不影响报告顺序。
    indexed_cases = [dict(case, _benchmark_index=index) for index, case in enumerate(benchmark_cases, 1)]
    log_benchmark(
        "benchmark.job.start",
        component="run_benchmark",
        job_id=job_id,
        total=total,
        workers=workers,
        output_path=str(output_path),
        ok=True,
    )

    results: list[dict | None] = [None] * total
    if workers == 1:
        # 串行模式用于网页默认路径：行为最容易观察，也不会同时初始化多份模型。
        for index, case in enumerate(indexed_cases):
            result = _run_one_case(case, job_id, total)
            results[index] = result
            if progress_callback:
                progress_callback(_progress_event(result, index + 1, total))
    else:
        # 并行模式只改变 case 的执行顺序，不改变最终结果的原始排列顺序。
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(_run_one_case, case, job_id, total): index
                for index, case in enumerate(indexed_cases)
            }
            for completed, future in enumerate(
                concurrent.futures.as_completed(future_to_index),
                start=1,
            ):
                index = future_to_index[future]
                result = future.result()
                results[index] = result
                if progress_callback:
                    progress_callback(_progress_event(result, completed, total))

    final_results = [result for result in results if result is not None]
    correct = sum(1 for result in final_results if result["correct"])
    accuracy = correct / total if total else 0
    category_stats = _build_category_stats(final_results)

    print("==== Benchmark Result ====")
    print(f"Total Cases: {total}")
    print(f"Correct: {correct}")
    print(f"Accuracy: {accuracy:.4f}")
    print(f"Workers: {workers}")
    for category, stats in category_stats.items():
        category_accuracy = stats["correct"] / stats["total"] if stats["total"] else 0
        print(f"{category}: {stats['correct']}/{stats['total']} Accuracy = {category_accuracy:.4f}")
    _print_failed_cases(final_results)

    output_data = {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "category_stats": category_stats,
        "workers": workers,
        "results": final_results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nBenchmark results saved to: {output_path}")
    log_benchmark(
        "benchmark.job.end",
        component="run_benchmark",
        job_id=job_id,
        total=total,
        correct=correct,
        accuracy=accuracy,
        workers=workers,
        output_path=str(output_path),
        duration_ms=round((time.perf_counter() - job_start) * 1000, 2),
        ok=True,
    )
    return output_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行 Medical NLP benchmark")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="并行 worker 数；不传时读取 BENCH_WORKERS，默认 1",
    )
    args = parser.parse_args()
    run_benchmark(workers=args.workers)
