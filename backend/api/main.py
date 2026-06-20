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
from pathlib import Path
#拿到backend目录
BACKEND_DIR = Path(__file__).resolve().parents[1]
#把backend目录加入到python模块搜索路径
sys.path.append(str(BACKEND_DIR))

from api.schemas import ExpandRequest,ExpandResponse,SimpleExpandResponse,BenchmarkSummaryResponse,ErrorAnalysisSummaryResponse
from services.abbr_service import ABBRService
#导入FastAPI
from fastapi import FastAPI

#创建API应用对象
app = FastAPI(
    title = "Medical NLP Standardization API",
    description = "医学缩写扩写、术语标准化、Verification 与 Reflection API",
    version = "0.1.0"
)

#创建service对象
#创建ABBRService实例
#懒加载
service = None


def get_service():
    global service

    if service is None:
        service = ABBRService()

    return service


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

    final_result = result.get("final_result",{})

    return {
        "success": result.get(
            "success",
            False
        ),
        "expanded_text": final_result.get(
            "expanded_text",
            request.text
        ),
        "mappings": final_result.get(
            "mappings",
            []
        )
    }

