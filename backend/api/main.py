"""
别人发一个 HTTP 请求
↓
FastAPI 接收 text
↓
调用 ABBRService 做缩写扩写 + 校验 + 重试
↓
返回 JSON 结果
"""

#处理导入路径
import os
import sys
import json
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
#拿到backend目录
BACKEND_DIR = Path(__file__).resolve().parents[1]
#把backend目录加入到python模块搜索路径
sys.path.append(str(BACKEND_DIR))

from api.schemas import (
    AnalysisDiagnoseRequest,
    AnalysisDiagnoseResponse,
    BenchmarkSummaryResponse,
    ErrorAnalysisSummaryResponse,
    ExpandRequest,
    ExpandResponse,
    SimpleExpandResponse,
)
from services.abbr_service import ABBRService
from services.diagnosis_explainer import explain_single_analysis
from data.abbr_candidates import ABBR_CANDIDATES
from evaluation.apply_fallback_candidate_promotions import (
    DEFAULT_CANDIDATES_FILE,
    DEFAULT_INPUT,
    apply_text_append,
    load_abbr_candidates,
    load_approved_items,
    norm_abbr,
    norm_expansion,
    plan_items,
)
#导入FastAPI
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

#创建API应用对象
app = FastAPI(
    title = "Medical NLP Standardization API",
    description = "医学缩写扩写、术语标准化、Verification 与 Reflection API",
    version = "0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount(
        "/frontend",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="frontend",
    )

#创建service对象
#创建ABBRService实例
#懒加载
service = None
BENCHMARK_JOBS = {}
BENCHMARK_JOBS_LOCK = threading.Lock()


def get_service():
    global service

    if service is None:
        service = ABBRService()

    return service


def _set_benchmark_job(job_id: str, **updates):
    with BENCHMARK_JOBS_LOCK:
        job = BENCHMARK_JOBS.setdefault(job_id, {})
        job.update(updates)
        job["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return dict(job)


def _get_benchmark_job(job_id: str):
    with BENCHMARK_JOBS_LOCK:
        job = BENCHMARK_JOBS.get(job_id)
        return dict(job) if job else None


# 当有人用 GET 方法访问 "/" 这个路径时
# 请执行 root() 这个函数
@app.get("/")
def root():
    return{
        "message":"Medical NLP Standardization API is running.",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health")
def health_check():
    return{
        "status": "ok",
        "service": "Medical NLP Standardization API",
        "version": "0.1.0",
        "checks": {
            "api": "ok"
        },
        "note": "This endpoint only checks whether the API server is running. Milvus and LLM are initialized on first request."
    }


@app.get("/app", response_class=HTMLResponse)
def frontend_app():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            "<h1>Frontend not found</h1><p>Expected frontend/index.html.</p>",
            status_code=404,
        )

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/benchmark/summary", response_model=BenchmarkSummaryResponse)
def get_benchmark_summary():
    benchmark_path = BACKEND_DIR / "evaluation" / "benchmark_results.json"

    if not benchmark_path.exists():
        return {
            "total_cases": 0,
            "correct": 0,
            "accuracy": 0.0,
            "category_stats": {}
        }

    with open(benchmark_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {
        "total_cases": data.get("total", 0),
        "correct": data.get("correct", 0),
        "accuracy": data.get("accuracy", 0.0),
        "category_stats": data.get("category_stats", {})
    }


@app.get("/benchmark/results")
def get_benchmark_results():
    benchmark_path = BACKEND_DIR / "evaluation" / "benchmark_results.json"

    if not benchmark_path.exists():
        return {
            "total": 0,
            "correct": 0,
            "accuracy": 0.0,
            "category_stats": {},
            "results": [],
        }

    with open(benchmark_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_uploaded_cases(payload) -> list[dict]:
    if isinstance(payload, list):
        cases = payload
    elif isinstance(payload, dict):
        cases = payload.get("cases")
    else:
        raise HTTPException(status_code=400, detail="Uploaded benchmark cases must be a list or an object with cases.")

    if not isinstance(cases, list) or not cases:
        raise HTTPException(status_code=400, detail="Uploaded benchmark cases must contain a non-empty cases list.")

    normalized_cases = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise HTTPException(status_code=400, detail=f"cases[{index - 1}] must be an object.")
        if not case.get("text"):
            raise HTTPException(status_code=400, detail=f"cases[{index - 1}] missing text.")
        expected = case.get("expected_mappings")
        if expected is None:
            raise HTTPException(status_code=400, detail=f"cases[{index - 1}] missing expected_mappings.")
        if not isinstance(expected, list):
            raise HTTPException(status_code=400, detail=f"cases[{index - 1}].expected_mappings must be a list.")

        normalized_cases.append({
            "id": case.get("id") or f"uploaded_case_{index:03d}",
            "category": case.get("category") or "uploaded",
            "text": case["text"],
            "expected_mappings": expected,
            **({"expected_text_contains": case.get("expected_text_contains")} if case.get("expected_text_contains") else {}),
        })

    return normalized_cases


def _run_benchmark_postprocess(progress_callback=None) -> dict:
    from evaluation import collect_fallback_candidate_promotions
    from evaluation import error_analysis_report
    from evaluation import error_triage

    steps = []

    if progress_callback:
        progress_callback("error_analysis_report", "正在生成错误分析数据", 72)
    error_analysis_report.main()
    steps.append({
        "name": "error_analysis_report",
        "ok": True,
        "path": str(BACKEND_DIR / "evaluation" / "error_analysis_report.json"),
    })

    if progress_callback:
        progress_callback("error_triage", "正在生成 LLM 错误解读", 82)
    error_triage.main()
    steps.append({
        "name": "error_triage",
        "ok": True,
        "path": str(BACKEND_DIR / "logs" / "triage" / "error_triage_report.md"),
    })

    if progress_callback:
        progress_callback("fallback_promotions", "正在沉淀 fallback 候选", 94)
    benchmark_path = BACKEND_DIR / "evaluation" / "benchmark_results.json"
    benchmark_data = json.loads(benchmark_path.read_text(encoding="utf-8"))
    promotions_report = collect_fallback_candidate_promotions.build_report(
        benchmark_data,
        benchmark_path,
    )
    promotions_json = BACKEND_DIR / "evaluation" / "fallback_candidate_promotions.json"
    promotions_md = BACKEND_DIR / "evaluation" / "fallback_candidate_promotions.md"
    promotions_json.write_text(
        json.dumps(promotions_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    promotions_md.write_text(
        collect_fallback_candidate_promotions.render_markdown(promotions_report),
        encoding="utf-8",
    )
    steps.append({
        "name": "fallback_candidate_promotions",
        "ok": True,
        "path": str(promotions_json),
        "total_items": promotions_report.get("total_items", 0),
        "new_item_count": promotions_report.get("new_item_count", 0),
    })

    return {
        "ok": True,
        "steps": steps,
    }


def _run_benchmark_case_job(job_id: str, cases: list[dict]):
    from evaluation.run_benchmark import run_benchmark

    benchmark_path = BACKEND_DIR / "evaluation" / "benchmark_results.json"

    try:
        _set_benchmark_job(
            job_id,
            status="running",
            stage="preparing",
            message="正在准备 benchmark 运行",
            progress=6,
            current=0,
            total=len(cases),
        )

        def benchmark_progress(event):
            total = event.get("total") or len(cases) or 1
            current = event.get("current") or 0
            progress = 10 + int((current / total) * 58)
            _set_benchmark_job(
                job_id,
                status="running",
                stage="running_benchmark",
                message=f"正在运行 benchmark cases: {current}/{total} ({event.get('case_id')})",
                progress=min(progress, 68),
                current=current,
                total=total,
                case_id=event.get("case_id"),
                category=event.get("category"),
            )

        run_benchmark(
            cases=cases,
            output_path=benchmark_path,
            progress_callback=benchmark_progress,
        )

        _set_benchmark_job(
            job_id,
            status="running",
            stage="saving_results",
            message="正在保存 benchmark_results.json",
            progress=70,
            current=len(cases),
            total=len(cases),
        )

        normalized_data = json.loads(benchmark_path.read_text(encoding="utf-8"))
        normalized_data["source"] = "uploaded_cases"
        normalized_data["uploaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        benchmark_path.write_text(
            json.dumps(normalized_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        def postprocess_progress(stage, message, progress):
            _set_benchmark_job(
                job_id,
                status="running",
                stage=stage,
                message=message,
                progress=progress,
                current=len(cases),
                total=len(cases),
            )

        postprocess = _run_benchmark_postprocess(postprocess_progress)

        result = {
            "ok": True,
            "path": str(benchmark_path),
            "total": normalized_data["total"],
            "correct": normalized_data["correct"],
            "accuracy": normalized_data["accuracy"],
            "category_count": len(normalized_data["category_stats"]),
            "uploaded_at": normalized_data["uploaded_at"],
            "postprocess": postprocess,
        }
        _set_benchmark_job(
            job_id,
            status="completed",
            stage="completed",
            message="上传 benchmark cases 已运行完成",
            progress=100,
            current=len(cases),
            total=len(cases),
            result=result,
        )
    except Exception as exc:
        _set_benchmark_job(
            job_id,
            status="failed",
            stage="failed",
            message="benchmark cases 运行失败",
            progress=100,
            error=str(exc),
            traceback=traceback.format_exc(),
            current=0,
            total=len(cases),
        )


@app.post("/benchmark/cases/run")
def upload_and_run_benchmark_cases(payload: dict):
    from evaluation.run_benchmark import run_benchmark

    cases = _load_uploaded_cases(payload)
    benchmark_path = BACKEND_DIR / "evaluation" / "benchmark_results.json"

    run_benchmark(cases=cases, output_path=benchmark_path)
    normalized_data = json.loads(benchmark_path.read_text(encoding="utf-8"))
    normalized_data["source"] = "uploaded_cases"
    normalized_data["uploaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    benchmark_path.write_text(
        json.dumps(normalized_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    try:
        postprocess = _run_benchmark_postprocess()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Benchmark cases ran, but postprocess failed.",
                "error": str(exc),
                "benchmark_path": str(benchmark_path),
            },
        ) from exc

    return {
        "ok": True,
        "path": str(benchmark_path),
        "total": normalized_data["total"],
        "correct": normalized_data["correct"],
        "accuracy": normalized_data["accuracy"],
        "category_count": len(normalized_data["category_stats"]),
        "uploaded_at": normalized_data["uploaded_at"],
        "postprocess": postprocess,
    }


@app.post("/benchmark/cases/jobs")
def create_benchmark_cases_job(payload: dict):
    cases = _load_uploaded_cases(payload)
    job_id = uuid.uuid4().hex
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _set_benchmark_job(
        job_id,
        id=job_id,
        status="queued",
        stage="queued",
        message=f"已读取上传文件，准备运行 {len(cases)} 个 benchmark cases",
        progress=2,
        current=0,
        total=len(cases),
        created_at=now,
    )

    worker = threading.Thread(
        target=_run_benchmark_case_job,
        args=(job_id, cases),
        daemon=True,
    )
    worker.start()

    return _get_benchmark_job(job_id)


@app.get("/benchmark/cases/jobs/{job_id}")
def get_benchmark_cases_job(job_id: str):
    job = _get_benchmark_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Benchmark job not found.")
    return job


@app.get(
    "/error-analysis/summary",
    response_model=ErrorAnalysisSummaryResponse
)
def get_error_analysis_summary():
    report_path = (
        BACKEND_DIR
        / "evaluation"
        / "error_analysis_report.json"
    )

    if not report_path.exists():
        return {
            "benchmark_summary": {},
            "failed_summary": {}
        }

    with open(report_path,"r",encoding="utf-8") as f:
        data = json.load(f)

    return {
        "benchmark_summary": data.get("benchmark_summary", {}),
        "failed_summary": data.get("failed_summary", {})
    }


@app.get("/error-analysis/report")
def get_error_analysis_report():
    report_path = BACKEND_DIR / "evaluation" / "error_analysis_report.json"

    if not report_path.exists():
        return {
            "benchmark_summary": {},
            "overall_failure_analysis": {},
            "failed_cases": [],
        }

    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/error-analysis/triage")
def get_error_triage_report():
    report_path = BACKEND_DIR / "logs" / "triage" / "error_triage_report.md"

    if not report_path.exists():
        return {
            "exists": False,
            "markdown": "",
        }

    with open(report_path, "r", encoding="utf-8") as f:
        markdown = f.read()

    return {
        "exists": True,
        "markdown": markdown,
    }


def refresh_promotion_status(promotions_data: dict) -> dict:
    candidates = load_abbr_candidates(DEFAULT_CANDIDATES_FILE)
    promotion_items = promotions_data.get("items", [])
    for item in promotion_items:
        abbr = norm_abbr(item.get("abbreviation"))
        expansion = norm_expansion(
            (item.get("candidate_to_append") or {}).get("expansion")
            or item.get("expansion")
        )
        item["already_exists"] = any(
            norm_expansion(candidate.get("expansion")) == expansion
            for candidate in candidates.get(abbr, [])
        )
    promotions_data["new_item_count"] = sum(
        1 for item in promotion_items if not item.get("already_exists")
    )
    promotions_data["already_exists_count"] = sum(
        1 for item in promotion_items if item.get("already_exists")
    )
    return promotions_data


def apply_items_to_primary(items: list[dict]) -> dict:
    candidates_path = DEFAULT_CANDIDATES_FILE
    source_text = candidates_path.read_text(encoding="utf-8")
    candidates = load_abbr_candidates(candidates_path)
    result = plan_items(candidates, items)
    batch_note = (
        "Added from fallback_candidate_promotions at "
        + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    if result["appended"]:
        updated = apply_text_append(source_text, result["appended"], batch_note)
        candidates_path.write_text(updated, encoding="utf-8")
        ABBR_CANDIDATES.clear()
        ABBR_CANDIDATES.update(candidates)

    return {
        "ok": True,
        "message": "candidate promotions applied.",
        "batch_note": batch_note,
        "appended_count": len(result["appended"]),
        "skipped_count": len(result["skipped"]),
        "appended": result["appended"],
        "skipped": result["skipped"],
        "updated": str(candidates_path),
    }


@app.get("/candidate-promotions")
def get_candidate_promotions():
    promotions_path = (
        BACKEND_DIR
        / "evaluation"
        / "fallback_candidate_promotions.json"
    )

    if not promotions_path.exists():
        return {
            "source_result_file": "",
            "selection_rule": "",
            "total_items": 0,
            "new_item_count": 0,
            "already_exists_count": 0,
            "items": [],
        }

    with open(promotions_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return refresh_promotion_status(data)


@app.post("/candidate-promotions/apply")
def apply_candidate_promotions():
    promotions_path = DEFAULT_INPUT

    if not promotions_path.exists():
        return {
            "ok": False,
            "message": "fallback_candidate_promotions.json not found.",
            "appended_count": 0,
            "skipped_count": 0,
            "appended": [],
            "skipped": [],
        }

    items = load_approved_items(promotions_path)
    apply_result = apply_items_to_primary(items)

    promotions_data = refresh_promotion_status(
        json.loads(promotions_path.read_text(encoding="utf-8"))
    )
    promotions_path.write_text(
        json.dumps(promotions_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        **apply_result,
    }


@app.post("/candidate-promotions/apply-single")
def apply_single_candidate_promotion(item: dict):
    return apply_items_to_primary([item])


@app.post("/analysis/diagnose", response_model=AnalysisDiagnoseResponse)
def diagnose_single_analysis(request: AnalysisDiagnoseRequest):
    return explain_single_analysis(
        text=request.text,
        analysis_result=request.analysis_result,
    )


"""
当有人用 POST 方法访问 /expand
FastAPI 会接收对方传来的 JSON
并把 JSON 转成 ExpandRequest 对象
然后执行 expand_abbreviation()
"""

#这里使用post是因为/expand不是简单查看需要提交数据给服务器处理
#response_model=ExpandResponse意思为这个接口返回的数据格式，要符合ExpandResponse
#request:ExpandRequest意为：请求体必须符合ExpandRequest这个模型
"""用户提交：
Patient has SOB and CP.

FastAPI 拿到 request.text

传给 ABBRService：

service.expand_verify_with_retry(
    text="Patient has SOB and CP.",
    max_retries=2
)"""
#开发者(完整调试版)
# @app.post("/expand",response_model = ExpandResponse)
# def expand_abberviation(request:ExpandRequest):
#     result = service.expand_verify_with_retry(
#         text = request.text,
#         max_retries=2
#     )
#     final_result = result.get("final_result",{})
#     #最后return 返回给调用接口的人
#     return {
#     "success": result.get("success", False),
#     "expanded_text": final_result.get("expanded_text", request.text),
#     "mappings": final_result.get("mappings", []),
#     "verification": result.get("verification"),
#     "attempts": result.get("attempts")
# }

#简单版
@app.post("/expand/simple",response_model=SimpleExpandResponse)
def expand_abbreviation_simple(
        request: ExpandRequest
):
    abbr_service = get_service()

    result = abbr_service.expand_verify_with_retry(
        text=request.text,
        max_retries=2
    )

    final_result = result.get("final_result", {}) or {}

    # 只输出 verify 判定为忠实标准化的 SNOMED 概念
    standardized_entities = []
    for ms in final_result.get("mapping_standardizations", []):
        top = ms.get("chosen_concept")
        if not top:
            continue
        standardized_entities.append({
            "abbreviation": ms.get("abbreviation"),
            "expansion": ms.get("expansion"),
            "concept_id": top.get("concept_id"),
            "concept_name": top.get("concept_name"),
            "concept_code": top.get("concept_code"),
            "domain_id": top.get("domain_id"),
            "score": top.get("score"),
        })

    return {
        "success": result.get(
            "success",
            False
        ),
        "expansion_success": result.get(
            "expansion_success",
            False
        ),
        "standardization_success": result.get(
            "standardization_success",
            False
        ),
        "success_breakdown": result.get(
            "success_breakdown"
        ),
        "expanded_text": final_result.get(
            "expanded_text",
            request.text
        ),
        "mappings": final_result.get(
            "mappings",
            []
        ),
        "standardized_entities": standardized_entities,
        "mapping_states": final_result.get(
            "mapping_states",
            []
        ),
    }

