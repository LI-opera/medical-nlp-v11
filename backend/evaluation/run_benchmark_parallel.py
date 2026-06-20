"""
并行版 benchmark 运行器
================================================================
和 run_benchmark.py 的【评分/报告逻辑完全一致】,只把【执行方式】从串行改成并行。
为什么能并行:每个 case 互相独立;瓶颈是等 DeepSeek API 回包(I/O),
多个 case 同时发请求、把"干等"的时间重叠起来,就能快几倍。

跑法:  python backend/evaluation/run_benchmark_parallel.py
调并发:改下面的 MAX_WORKERS(从 4 起步,太高会被 DeepSeek 限流)。
"""

import os
import sys
import json
import time
import threading
import concurrent.futures
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from evaluation.abbr_benchmark_cases import ABBR_BENCHMARK_CASES
from evaluation.concept_match import compare_mappings_snomed, normalize_text
from services.abbr_service import ABBRService

# 并发数:同时跑几个 case。I/O 密集,4 个一般够;太高 DeepSeek 会限流(429/断连)。
# 也可以用环境变量覆盖:set BENCH_WORKERS=6
MAX_WORKERS = int(os.getenv("BENCH_WORKERS", "4"))


# ── 每个线程一份独立的 ABBRService ────────────────────────────────
# 为什么:ABBRService 内部有 HuggingFace NER pipeline、bge-m3 embedding、
# Milvus client,它们【不保证线程安全】。若所有线程共用一个 service,多线程
# 同时调这些模型可能出错或返回错结果,悄悄污染 benchmark。
# threading.local() = "线程本地存储":每个线程第一次用时各自 new 一个 service
# 并缓存在自己名下,之后复用;线程之间互不干扰。
# 代价:每个 worker 各加载一份模型(N 份内存,bge-m3 约 2GB/份)。
_tls = threading.local()


def get_service():
    svc = getattr(_tls, "svc", None)
    if svc is None:
        svc = ABBRService()          # 当前线程第一次调用时才创建
        _tls.svc = svc
    return svc


# ── 下面三个函数和串行版逐字相同(评分口径不变)──────────────────
def compare_text_contains(final_text, expected_text_contains):
    if not expected_text_contains:
        return {"checked": False, "correct": True,
                "expected_text_contains": expected_text_contains, "final_text": final_text}
    if final_text is None:
        final_text = ""
    if not isinstance(final_text, str):
        final_text = str(final_text)
    correct = normalize_text(expected_text_contains) in normalize_text(final_text)
    return {"checked": True, "correct": correct,
            "expected_text_contains": expected_text_contains, "final_text": final_text}


def run_one_case(case):
    """跑单个 case → 返回它的结果 dict。会被多个线程并发调用。"""
    service = get_service()           # 拿到【本线程】的 service

    # per-case 重试:某次网络瞬断只影响这一个 case,不拖垮整轮
    result = None
    for _try in range(3):
        try:
            result = service.expand_verify_with_retry(text=case["text"], max_retries=2)
            break
        except Exception as e:
            if _try == 2:
                print(f"[WARN] {case['id']} failed after retries: {e}")
                result = {"final_result": {}, "success": False, "error": str(e)}
            else:
                time.sleep(3)

    final_result = result.get("final_result", {}) or {}
    predicted_mappings = final_result.get("mappings", [])
    final_expanded_text = final_result.get("expanded_text", "")

    is_correct = compare_mappings_snomed(service, case["expected_mappings"], predicted_mappings)
    text_check = compare_text_contains(final_expanded_text, case.get("expected_text_contains"))
    final_correct = is_correct and text_check["correct"]

    return {
        "id": case["id"], "category": case["category"], "text": case["text"],
        "success": result.get("success"),
        "expected_mappings": case["expected_mappings"],
        "predicted_mappings": predicted_mappings,
        "final_expanded_text": final_expanded_text,
        "mapping_correct": is_correct, "text_check": text_check, "correct": final_correct,
    }


def run_benchmark():
    total = len(ABBR_BENCHMARK_CASES)
    # 预留一个和 case 等长的列表,按【原始顺序】回填结果 → 报告稳定可复现
    results = [None] * total

    print(f"Running {total} cases with {MAX_WORKERS} workers ...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        # submit 把每个 case 丢进线程池,返回一个 future(未来的结果句柄)
        # 记下 future → 它对应第几个 case,好把结果放回正确的位置
        future_to_idx = {ex.submit(run_one_case, case): i
                         for i, case in enumerate(ABBR_BENCHMARK_CASES)}
        done = 0
        # as_completed:谁先跑完先返回谁(顺序是乱的,所以才要 future_to_idx 定位)
        for fut in concurrent.futures.as_completed(future_to_idx):
            i = future_to_idx[fut]
            results[i] = fut.result()
            done += 1
            print(f"  [{done}/{total}] {results[i]['id']}")

    # ── 下面汇总 + 打印 + 存盘,和串行版完全一致 ──
    correct = sum(1 for r in results if r["correct"])
    category_stats = {}
    for r in results:
        c = r["category"]
        if c not in category_stats:
            category_stats[c] = {"total": 0, "correct": 0}
        category_stats[c]["total"] += 1
        if r["correct"]:
            category_stats[c]["correct"] += 1

    accuracy = correct / total if total > 0 else 0

    print("\n==== Benchmark Result ====")
    print(f"Total Cases:{total}")
    print(f"Correct:{correct}")
    print(f"Expansion Accuracy:{accuracy:.4f}")

    print("\n ==== Category Results ====")
    for category, stats in category_stats.items():
        category_accuracy = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
        print(f"{category}:{stats['correct']}/{stats['total']}  Accuracy = {category_accuracy:.4f}")

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
        json.dump({"total": total, "correct": correct, "accuracy": accuracy,
                   "category_stats": category_stats, "results": results},
                  f, ensure_ascii=False, indent=2)
    print(f"\nBenchmark results saved to: {output_path}")


if __name__ == "__main__":
    run_benchmark()
