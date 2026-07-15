import pytest

from evaluation.run_benchmark import _build_category_stats, compare_text_contains, normalize_text
from services.abbr_service import ABBRService


pytestmark = pytest.mark.unit


def test_success_breakdown_requires_all_records_coded_for_standardization():
    records = [
        {"expansion": "shortness of breath", "status": "CODED"},
        {"expansion": "chest pain", "status": "WITHHELD"},
    ]

    breakdown = ABBRService._build_success_breakdown(records)

    assert breakdown["target_count"] == 2
    assert breakdown["expanded_count"] == 2
    assert breakdown["coded_count"] == 1
    assert breakdown["withheld_count"] == 1
    assert breakdown["expansion_success"] is True
    assert breakdown["standardization_success"] is False


def test_success_breakdown_empty_records_is_not_success():
    breakdown = ABBRService._build_success_breakdown([])

    assert breakdown["target_count"] == 0
    assert breakdown["expansion_success"] is False
    assert breakdown["standardization_success"] is False


def test_deterministic_expansion_obeys_token_boundaries_and_multiple_records():
    text = "Patient has CP and MS; CPR was performed."
    chosen = [
        {"abbreviation": "CP", "expansion": "chest pain"},
        {"abbreviation": "MS", "expansion": "mitral stenosis"},
    ]

    assert ABBRService._build_expanded_text_deterministic(None, text, chosen) == (
        "Patient has chest pain and mitral stenosis; CPR was performed."
    )


def test_benchmark_text_check_is_case_insensitive_and_trimmed():
    assert normalize_text("  SOB ") == "sob"
    result = compare_text_contains("Patient has Shortness of Breath.", "shortness of breath")

    assert result["checked"] is True
    assert result["correct"] is True


def test_benchmark_category_stats_counts_total_and_correct():
    results = [
        {"category": "single_meaning", "correct": True},
        {"category": "single_meaning", "correct": False},
        {"category": "ambiguous", "correct": True},
    ]

    assert _build_category_stats(results) == {
        "single_meaning": {"total": 2, "correct": 1},
        "ambiguous": {"total": 1, "correct": 1},
    }
