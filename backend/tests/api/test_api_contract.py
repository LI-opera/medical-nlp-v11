import pytest
from fastapi.testclient import TestClient

import api.main as api_main


pytestmark = pytest.mark.unit


class FakeService:
    def expand_verify_with_retry(self, text: str, max_retries: int):
        return {
            "success": True,
            "expansion_success": True,
            "standardization_success": True,
            "success_breakdown": {"target_count": 1, "coded_count": 1},
            "final_result": {
                "expanded_text": "Patient has shortness of breath.",
                "mappings": [
                    {"abbreviation": "SOB", "expansion": "shortness of breath"}
                ],
                "mapping_states": [
                    {"abbreviation": "SOB", "status": "CODED"}
                ],
                "mapping_standardizations": [
                    {
                        "abbreviation": "SOB",
                        "expansion": "shortness of breath",
                        "chosen_concept": {
                            "concept_id": "1",
                            "concept_name": "Dyspnea",
                            "concept_code": "267036007",
                            "domain_id": "Condition",
                            "score": 1.0,
                        },
                    }
                ],
            },
        }


def test_health_endpoint_is_available():
    response = TestClient(api_main.app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_frontend_log_rejects_invalid_payload():
    response = TestClient(api_main.app).post("/frontend-log", json={"logs": "bad"})

    assert response.status_code == 400
    assert "logs: list" in response.json()["detail"]


def test_expand_simple_contract_and_request_id(monkeypatch):
    monkeypatch.setattr(api_main, "get_service", lambda: FakeService())

    response = TestClient(api_main.app).post(
        "/expand/simple",
        headers={"X-Frontend-Request-Id": "frontend-test-1"},
        json={"text": "Patient has SOB."},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["request_id"].startswith("ana_")
    assert body["expanded_text"] == "Patient has shortness of breath."
    assert body["standardized_entities"][0]["concept_name"] == "Dyspnea"
