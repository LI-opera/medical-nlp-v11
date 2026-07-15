import os

import pytest


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE") != "1",
        reason="Set RUN_LIVE=1 to call the real model, Milvus, and LLM services.",
    ),
]


def test_live_abbreviation_pipeline_returns_structured_result():
    from services.abbr_service import ABBRService

    result = ABBRService().expand_verify_with_retry(
        text="The patient has SOB and CP.",
        max_retries=2,
    )

    assert isinstance(result, dict)
    assert isinstance(result.get("final_result"), dict)
    assert "success" in result
    assert "expansion_success" in result
    assert "standardization_success" in result
