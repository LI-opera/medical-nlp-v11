import time

import torch
from langchain_huggingface import HuggingFaceEmbeddings

from utils.embedding_config import EmbeddingConfig, EmbeddingProvider
from utils.structured_logger import exc_meta, log_dependency


def create_embedding_model(config: EmbeddingConfig):
    """Create the embedding model from config."""
    start = time.perf_counter()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log_dependency(
        "dependency.embedding.load_start",
        component="embedding_factory",
        provider=str(config.provider),
        model_name=config.model_name,
        device=device,
        ok=True,
    )

    if config.provider == EmbeddingProvider.HUGGINGFACE:
        try:
            model = HuggingFaceEmbeddings(
                model_name=config.model_name,
                model_kwargs={
                    "device": device,
                    "trust_remote_code": True,
                },
                encode_kwargs={
                    "normalize_embeddings": True,
                },
            )
            log_dependency(
                "dependency.embedding.load_ok",
                component="embedding_factory",
                provider=str(config.provider),
                model_name=config.model_name,
                device=device,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                ok=True,
            )
            return model
        except Exception as exc:
            log_dependency(
                "dependency.embedding.load_error",
                component="embedding_factory",
                provider=str(config.provider),
                model_name=config.model_name,
                device=device,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                ok=False,
                level="ERROR",
                **exc_meta(exc),
            )
            raise

    try:
        raise ValueError(f"Unsupported embedding provider:{config.provider}")
    except ValueError as exc:
        log_dependency(
            "dependency.embedding.load_error",
            component="embedding_factory",
            provider=str(config.provider),
            model_name=config.model_name,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            ok=False,
            level="ERROR",
            **exc_meta(exc),
        )
        raise
