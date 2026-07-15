import pytest

from evaluation.performance_report import (
    build_performance_report,
    percentile,
    summarize_latencies,
)


pytestmark = pytest.mark.unit


def test_percentile_uses_linear_interpolation():
    assert percentile([10, 20, 30, 40], 50) == 25.0
    assert percentile([10, 20, 30, 40], 95) == 38.5
    assert percentile([], 95) is None


def test_latency_summary_has_stable_core_statistics():
    assert summarize_latencies([10, 20, 30]) == {
        "count": 3,
        "average_ms": 20.0,
        "p50_ms": 20.0,
        "p95_ms": 29.0,
        "max_ms": 30.0,
    }


def test_build_report_separates_case_latency_and_unavailable_stage_latency():
    benchmark_data = {
        "total": 2,
        "correct": 1,
        "accuracy": 0.5,
        "workers": 2,
        "results": [
            {"id": "case_1", "category": "single_meaning", "correct": True},
            {"id": "case_2", "category": "coverage_failed", "correct": False},
        ],
    }
    benchmark_events = [
        {"event": "benchmark.job.start", "job_id": "bench_1", "workers": 2},
        {"event": "benchmark.case.end", "job_id": "bench_1", "case_id": "case_1", "category": "single_meaning", "duration_ms": 100},
        {"event": "benchmark.case.end", "job_id": "bench_1", "case_id": "case_2", "category": "coverage_failed", "duration_ms": 300},
        {"event": "benchmark.job.end", "job_id": "bench_1", "workers": 2, "duration_ms": 350},
    ]

    report = build_performance_report(benchmark_data, benchmark_events)

    assert report["job"]["duration_ms"] == 350.0
    assert report["job"]["duration_source"] == "benchmark.job.end"
    assert report["job"]["throughput_cases_per_second"] == 5.714
    assert report["cases"]["latency"]["average_ms"] == 200.0
    assert report["cases"]["category_latency"]["coverage_failed"]["latency"]["max_ms"] == 300.0
    assert report["stages"]["available"] is False


def test_stage_summary_only_uses_explicit_duration_records():
    report = build_performance_report(
        {"total": 0, "results": []},
        [],
        dependency_events=[{"event": "milvus.search", "duration_ms": 12.5}],
    )

    assert report["stages"]["available"] is True
    assert report["stages"]["stages"]["milvus.search"]["average_ms"] == 12.5
