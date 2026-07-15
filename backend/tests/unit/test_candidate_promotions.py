import pytest

import evaluation.collect_fallback_candidate_promotions as promotions


pytestmark = pytest.mark.unit


def test_collect_items_keeps_multiple_expansions_and_deduplicates_support():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(promotions, "ABBR_CANDIDATES", {})
    try:
        data = {
            "results": [
                {
                    "id": "case_1",
                    "category": "fallback_should_expand",
                    "text": "Patient has ABG.",
                    "correct": True,
                    "mapping_states": [
                        {
                            "abbreviation": "ABG",
                            "expansion": "arterial blood gas",
                            "source": "fallback",
                            "status": "CODED",
                            "domain": "Measurement",
                        }
                    ],
                    "mapping_standardizations": [
                        {
                            "abbreviation": "ABG",
                            "expansion": "arterial blood gas",
                            "chosen_concept": {"concept_id": "1", "concept_name": "Blood gas"},
                        }
                    ],
                },
                {
                    "id": "case_2",
                    "category": "fallback_should_expand",
                    "text": "Patient has ABG.",
                    "correct": True,
                    "mapping_states": [
                        {
                            "abbreviation": "ABG",
                            "expansion": "arterial blood gas",
                            "source": "fallback",
                            "status": "CODED",
                            "domain": "Measurement",
                        }
                    ],
                    "mapping_standardizations": [
                        {
                            "abbreviation": "ABG",
                            "expansion": "arterial blood gas",
                            "chosen_concept": {"concept_id": "1", "concept_name": "Blood gas"},
                        }
                    ],
                },
            ]
        }

        items = promotions.collect_items(data)

        assert len(items) == 1
        assert items[0]["abbreviation"] == "ABG"
        assert items[0]["support_count"] == 2
        assert items[0]["case_ids"] == ["case_1", "case_2"]
    finally:
        monkeypatch.undo()


def test_collect_items_ignores_incorrect_or_non_coded_records():
    data = {
        "results": [
            {
                "id": "wrong",
                "correct": False,
                "mapping_states": [
                    {"abbreviation": "ABG", "expansion": "arterial blood gas", "source": "fallback", "status": "CODED"}
                ],
            },
            {
                "id": "withheld",
                "correct": True,
                "mapping_states": [
                    {"abbreviation": "ABG", "expansion": "arterial blood gas", "source": "fallback", "status": "WITHHELD"}
                ],
            },
        ]
    }

    assert promotions.collect_items(data) == []
