"""从 Benchmark 结果和结构化日志生成轻量性能报告。

本模块只读取已有产物，不参与 Benchmark 执行，也不改变准确率判定。
没有明确的 ``duration_ms`` 时，报告会标记指标不可用，不会估算阶段耗时。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from evaluation.paths import (  # noqa: E402
    BENCHMARK_RESULTS_PATH,
    PERFORMANCE_REPORT_JSON_PATH,
    PERFORMANCE_REPORT_MD_PATH,
)


def read_jsonl(path: Path) -> tuple[list[dict], int]:
    """读取 JSONL，并返回记录与坏行数量。日志轮转/尾部损坏不应阻断报告。"""
    if not path.exists():
        return [], 0
    records: list[dict] = []
    errors = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
        except json.JSONDecodeError:
            errors += 1
    return records, errors


def percentile(values: Iterable[float], percentile_value: float) -> float | None:
    """使用线性插值计算 P50/P95，空输入返回 None。"""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * percentile_value / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    result = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return round(result, 2)


def summarize_latencies(values: Iterable[float]) -> dict[str, Any]:
    numbers = [float(value) for value in values]
    return {
        "count": len(numbers),
        "average_ms": round(sum(numbers) / len(numbers), 2) if numbers else None,
        "p50_ms": percentile(numbers, 50),
        "p95_ms": percentile(numbers, 95),
        "max_ms": round(max(numbers), 2) if numbers else None,
    }


def _duration_records(events: Iterable[dict], event_name: str) -> list[dict]:
    return [
        event
        for event in events
        if event.get("event") == event_name and isinstance(event.get("duration_ms"), (int, float))
    ]


def _stage_summary(dependency_events: list[dict], pipeline_events: list[dict]) -> dict:
    events = dependency_events + pipeline_events
    measured = [event for event in events if isinstance(event.get("duration_ms"), (int, float))]
    if not measured:
        return {
            "available": False,
            "reason": "missing_explicit_stage_duration_log",
            "sample_count": 0,
            "stages": {},
        }
    groups: dict[str, list[float]] = defaultdict(list)
    for event in measured:
        event_name = str(event.get("event", "unknown"))
        groups[event_name].append(float(event["duration_ms"]))
    return {
        "available": True,
        "reason": None,
        "sample_count": len(measured),
        "stages": {name: summarize_latencies(values) for name, values in sorted(groups.items())},
    }


def build_performance_report(
    benchmark_data: dict,
    benchmark_events: list[dict],
    dependency_events: list[dict] | None = None,
    pipeline_events: list[dict] | None = None,
    *,
    log_parse_errors: int = 0,
) -> dict:
    """根据一次 Benchmark 结果构建可读、可追溯的性能摘要。"""
    dependency_events = dependency_events or []
    pipeline_events = pipeline_events or []
    job_end = _duration_records(benchmark_events, "benchmark.job.end")
    job_start = [event for event in benchmark_events if event.get("event") == "benchmark.job.start"]
    selected_job = job_end[-1] if job_end else (job_start[-1] if job_start else None)
    selected_job_id = selected_job.get("job_id") if selected_job else None
    all_case_end = _duration_records(benchmark_events, "benchmark.case.end")
    # 日志文件会保留多个历史 Benchmark；性能报告只对应结果文件所代表的最近一次作业。
    case_end = [
        event
        for event in all_case_end
        if selected_job_id is None or event.get("job_id") == selected_job_id
    ]
    request_ids = {event.get("request_id") for event in case_end if event.get("request_id")}
    scoped_dependency_events = [
        event
        for event in dependency_events
        if selected_job_id is None
        or (event.get("job_id") == selected_job_id)
        or (event.get("request_id") in request_ids)
    ]
    scoped_pipeline_events = [
        event
        for event in pipeline_events
        if selected_job_id is None
        or (event.get("job_id") == selected_job_id)
        or (event.get("request_id") in request_ids)
    ]

    result_rows = benchmark_data.get("results") or []
    category_by_id = {str(row.get("id")): row.get("category", "unknown") for row in result_rows}
    case_values = [float(event["duration_ms"]) for event in case_end]
    categories: dict[str, list[float]] = defaultdict(list)
    for event in case_end:
        category = event.get("category") or category_by_id.get(str(event.get("case_id")), "unknown")
        categories[str(category)].append(float(event["duration_ms"]))

    job_duration = float(job_end[-1]["duration_ms"]) if job_end else None
    duration_source = "benchmark.job.end" if job_duration is not None else None
    if job_duration is None and case_values:
        job_duration = sum(case_values)
        duration_source = "sum_case_duration"
    total = int(benchmark_data.get("total", len(result_rows)) or 0)
    throughput = round(total / (job_duration / 1000), 3) if job_duration else None

    category_report = {}
    for category, values in sorted(categories.items()):
        rows = [row for row in result_rows if str(row.get("category", "unknown")) == category]
        correct = sum(1 for row in rows if row.get("correct"))
        category_report[category] = {
            "total": len(rows),
            "correct": correct,
            "accuracy": round(correct / len(rows), 4) if rows else None,
            "latency": summarize_latencies(values),
        }

    return {
        "schema_version": "v1",
        "source": {
            "benchmark_total": total,
            "benchmark_log_records": len(benchmark_events),
            "log_parse_errors": log_parse_errors,
        },
        "job": {
            "job_id": selected_job_id,
            "workers": selected_job.get("workers") if selected_job else benchmark_data.get("workers"),
            "duration_ms": round(job_duration, 2) if job_duration is not None else None,
            "duration_source": duration_source,
            "throughput_cases_per_second": throughput,
        },
        "cases": {
            "latency": summarize_latencies(case_values),
            "category_latency": category_report,
        },
        "stages": _stage_summary(scoped_dependency_events, scoped_pipeline_events),
        "limitations": [
            "阶段耗时仅在 dependency/pipeline 日志显式记录 duration_ms 时统计。",
            "P95 基于本次日志中已记录的 case end 事件，不代表长期生产分位数。",
        ],
    }


def render_markdown(report: dict) -> str:
    job = report["job"]
    latency = report["cases"]["latency"]
    lines = [
        "# V11 Benchmark 性能报告",
        "",
        "> 本报告来自 Benchmark 结果与结构化日志，仅描述运行性能，不改变 accuracy 判定。",
        "",
        "## 作业概览",
        f"- 作业 ID：`{job.get('job_id') or '未知'}`",
        f"- worker 数：`{job.get('workers') or '未知'}`",
        f"- 总耗时：`{job.get('duration_ms') if job.get('duration_ms') is not None else '不可用'} ms`（来源：`{job.get('duration_source') or '无'}`）",
        f"- 吞吐：`{job.get('throughput_cases_per_second') if job.get('throughput_cases_per_second') is not None else '不可用'}` case/s",
        "",
        "## Case 延迟",
        f"- 有效样本：`{latency['count']}`",
        f"- 平均：`{latency['average_ms'] if latency['average_ms'] is not None else '不可用'} ms`",
        f"- P50：`{latency['p50_ms'] if latency['p50_ms'] is not None else '不可用'} ms`",
        f"- P95：`{latency['p95_ms'] if latency['p95_ms'] is not None else '不可用'} ms`",
        f"- 最大值：`{latency['max_ms'] if latency['max_ms'] is not None else '不可用'} ms`",
        "",
        "## 分类延迟与准确率",
        "| 分类 | cases | correct | accuracy | 平均 ms | P95 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category, data in report["cases"]["category_latency"].items():
        item = data["latency"]
        lines.append(f"| {category} | {data['total']} | {data['correct']} | {data['accuracy']} | {item['average_ms']} | {item['p95_ms']} |")
    lines.extend(["", "## 阶段耗时", f"- 可用：`{report['stages']['available']}`", f"- 说明：{report['stages']['reason'] or '已有显式阶段耗时记录。'}"])
    if report["stages"]["available"]:
        for stage, data in report["stages"]["stages"].items():
            lines.append(f"- `{stage}`：{data['count']} 次，平均 {data['average_ms']} ms，P95 {data['p95_ms']} ms")
    lines.extend(["", "## 口径说明", *[f"- {item}" for item in report["limitations"]], ""])
    return "\n".join(lines)


def generate_report(
    benchmark_path: Path = BENCHMARK_RESULTS_PATH,
    benchmark_log_path: Path | None = None,
    dependency_log_path: Path | None = None,
    pipeline_log_path: Path | None = None,
    json_output: Path = PERFORMANCE_REPORT_JSON_PATH,
    md_output: Path = PERFORMANCE_REPORT_MD_PATH,
) -> dict:
    benchmark_data = json.loads(benchmark_path.read_text(encoding="utf-8")) if benchmark_path.exists() else {}
    benchmark_events, parse_errors = read_jsonl(benchmark_log_path or BACKEND_DIR / "logs" / "benchmark.jsonl")
    dependency_events, dependency_errors = read_jsonl(dependency_log_path or BACKEND_DIR / "logs" / "dependency.jsonl")
    pipeline_events, pipeline_errors = read_jsonl(pipeline_log_path or BACKEND_DIR / "logs" / "pipeline.jsonl")
    report = build_performance_report(
        benchmark_data,
        benchmark_events,
        dependency_events,
        pipeline_events,
        log_parse_errors=parse_errors + dependency_errors + pipeline_errors,
    )
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_output.write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Benchmark 性能报告")
    parser.add_argument("--input", type=Path, default=BENCHMARK_RESULTS_PATH)
    parser.add_argument("--benchmark-log", type=Path)
    parser.add_argument("--dependency-log", type=Path)
    parser.add_argument("--pipeline-log", type=Path)
    parser.add_argument("--json-output", type=Path, default=PERFORMANCE_REPORT_JSON_PATH)
    parser.add_argument("--md-output", type=Path, default=PERFORMANCE_REPORT_MD_PATH)
    args = parser.parse_args()
    report = generate_report(args.input, args.benchmark_log, args.dependency_log, args.pipeline_log, args.json_output, args.md_output)
    print(render_markdown(report))


if __name__ == "__main__":
    main()
