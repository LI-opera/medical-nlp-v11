import os

import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1",
        reason="Set RUN_INTEGRATION=1 to run Docker/Milvus integration tests.",
    ),
]


def test_required_milvus_collections_are_available():
    from pymilvus import MilvusClient

    uri = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
    snomed = os.getenv("MILVUS_COLLECTION_NAME", "concepts_only_name")
    rxnorm = os.getenv("MILVUS_RXNORM_COLLECTION", "rxnorm_concepts")
    client = MilvusClient(uri=uri)

    assert client.has_collection(snomed), f"Missing SNOMED collection: {snomed}"
    assert client.has_collection(rxnorm), f"Missing RxNorm collection: {rxnorm}"
