from pydantic import BaseModel,Field

class ExpandRequest(BaseModel):
    """
    缩写扩写请求
    """
    text:str = Field(
        ...,
        description="输入的临床文本"
    )

class ExpandResponse(BaseModel):
    """
    缩写扩写响应
    """
    success:bool
    expansion_success: bool = False
    standardization_success: bool = False
    success_breakdown: dict | None = None
    expanded_text:str
    mappings:list[dict]
    verification:dict | None = None
    attempts:list[dict] | None = None

class SimpleExpandResponse(BaseModel):
    """
    简洁版扩写结果。
    """

    success: bool
    expansion_success: bool = False
    standardization_success: bool = False
    success_breakdown: dict | None = None
    expanded_text: str
    mappings: list[dict]
    standardized_entities: list[dict] = []
    mapping_states: list[dict] = []


class AnalysisDiagnoseRequest(BaseModel):
    """
    当前单句分析结果的人话诊断请求。
    """

    text: str
    analysis_result: dict


class AnalysisDiagnoseResponse(BaseModel):
    """
    当前单句分析结果的人话诊断响应。
    """

    summary: str = ""
    record_notes: list[dict] = []
    next_steps: list[str] = []


class BenchmarkSummaryResponse(BaseModel):
    """
    Benchmark 汇总结果响应。
    """

    total_cases: int
    correct: int
    accuracy: float
    category_stats: dict

class ErrorAnalysisSummaryResponse(BaseModel):
    """
    Error Analysis 汇总响应。
    """

    benchmark_summary: dict
    failed_summary: dict

