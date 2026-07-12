from __future__ import annotations

import contextlib
import contextvars
import uuid
from datetime import datetime


_request_id = contextvars.ContextVar("request_id", default=None)
_frontend_request_id = contextvars.ContextVar("frontend_request_id", default=None)
_job_id = contextvars.ContextVar("job_id", default=None)
_case_id = contextvars.ContextVar("case_id", default=None)


def _timestamp_id(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def new_request_id(prefix: str = "ana") -> str:
    # request_id 用来串起一次单句分析或一个 benchmark case 的服务调用；
    # job_id 归并整个长任务，case_id 标识该长任务中的具体输入。
    return _timestamp_id(prefix)


def new_job_id(prefix: str = "bench") -> str:
    return _timestamp_id(prefix)


def get_request_id() -> str | None:
    return _request_id.get()


def get_frontend_request_id() -> str | None:
    return _frontend_request_id.get()


def get_job_id() -> str | None:
    return _job_id.get()


def get_case_id() -> str | None:
    return _case_id.get()


def get_trace_fields() -> dict:
    return {
        "request_id": get_request_id(),
        "frontend_request_id": get_frontend_request_id(),
        "job_id": get_job_id(),
        "case_id": get_case_id(),
    }


@contextlib.contextmanager
def trace_context(
    request_id: str | None = None,
    frontend_request_id: str | None = None,
    job_id: str | None = None,
    case_id: str | None = None,
):
    request_token = _request_id.set(request_id) if request_id is not None else None
    frontend_request_token = (
        _frontend_request_id.set(frontend_request_id)
        if frontend_request_id is not None
        else None
    )
    job_token = _job_id.set(job_id) if job_id is not None else None
    case_token = _case_id.set(case_id) if case_id is not None else None
    try:
        yield
    finally:
        if case_token is not None:
            _case_id.reset(case_token)
        if job_token is not None:
            _job_id.reset(job_token)
        if frontend_request_token is not None:
            _frontend_request_id.reset(frontend_request_token)
        if request_token is not None:
            _request_id.reset(request_token)
