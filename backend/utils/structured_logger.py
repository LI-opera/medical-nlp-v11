from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from utils.trace_context import get_trace_fields


BACKEND_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BACKEND_DIR / "logs"

LOG_FILES = {
    "app": "app.jsonl",
    "dependency": "dependency.jsonl",
    "pipeline": "pipeline.jsonl",
    "benchmark": "benchmark.jsonl",
    "audit": "audit.jsonl",
    "frontend": "frontend.jsonl",
}

_LOGGERS: dict[str, logging.Logger] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _max_bytes() -> int:
    try:
        return max(1, int(os.getenv("LOG_MAX_FILE_MB", "10"))) * 1024 * 1024
    except ValueError:
        return 10 * 1024 * 1024


def _backup_count() -> int:
    try:
        return max(1, int(os.getenv("LOG_MAX_BACKUPS", "5")))
    except ValueError:
        return 5


def _get_logger(channel: str) -> logging.Logger | None:
    if channel in _LOGGERS:
        return _LOGGERS[channel]

    filename = LOG_FILES.get(channel)
    if not filename:
        return None

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(f"medical_nlp.{channel}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()
        handler = RotatingFileHandler(
            LOG_DIR / filename,
            maxBytes=_max_bytes(),
            backupCount=_backup_count(),
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        _LOGGERS[channel] = logger
        return logger
    except Exception as exc:  # pragma: no cover - logging must never break business
        print(f"[log-disabled] {channel}: {exc}", file=sys.stderr)
        return None


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(v) for v in value]
        return str(value)


def _truncate(value: Any, max_chars: int | None = None) -> Any:
    if not isinstance(value, str):
        return value
    if max_chars is None:
        try:
            max_chars = max(200, int(os.getenv("LOG_RAW_OUTPUT_MAX_CHARS", "2000")))
        except ValueError:
            max_chars = 2000
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"


def text_meta(text: str | None) -> dict:
    if text is None:
        return {"text_len": 0, "text_hash": None}
    meta = {
        "text_len": len(text),
        "text_hash": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    if _env_bool("LOG_TEXT_PREVIEW", default=False):
        meta["text_preview"] = text[:160]
    return meta


def exc_meta(exc: BaseException | None) -> dict:
    if exc is None:
        return {}
    return {
        "error_type": exc.__class__.__name__,
        "error": _truncate(str(exc), 1000),
        "traceback": _truncate(traceback.format_exc()),
    }


def log_event(
    channel: str,
    event: str,
    *,
    level: str = "INFO",
    component: str | None = None,
    ok: bool | None = None,
    **fields: Any,
) -> None:
    # 结构化 JSONL 是运行过程轨迹，用来补充 record.status、benchmark 结果和
    # 错误分析产物，不能替代这些面向业务的状态与报告。
    try:
        logger = _get_logger(channel)
        if logger is None:
            return

        payload = {
            "ts": _now_iso(),
            "level": level,
            "event": event,
            "component": component,
            **get_trace_fields(),
            "ok": ok,
            **fields,
        }
        payload = {k: _json_safe(v) for k, v in payload.items() if v is not None}
        logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except Exception as exc:  # pragma: no cover - logging must never break business
        print(f"[log-error] {channel}.{event}: {exc}", file=sys.stderr)


def log_app(event: str, **fields: Any) -> None:
    log_event("app", event, **fields)


def log_dependency(event: str, **fields: Any) -> None:
    log_event("dependency", event, **fields)


def log_pipeline(event: str, **fields: Any) -> None:
    log_event("pipeline", event, **fields)


def log_benchmark(event: str, **fields: Any) -> None:
    log_event("benchmark", event, **fields)


def log_audit(event: str, **fields: Any) -> None:
    log_event("audit", event, **fields)


def log_frontend(event: str, **fields: Any) -> None:
    log_event("frontend", event, **fields)
