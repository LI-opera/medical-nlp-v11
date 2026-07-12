from __future__ import annotations

import json
import time
from typing import Any

from utils.llm_config import DEEPSEEK_CONFIG
from utils.llm_factory import create_llm
from utils.structured_logger import exc_meta, log_dependency


def _strip_json_fence(content: str) -> str:
    return content.strip().replace("```json", "").replace("```", "").strip()


def invoke_json_llm(prompt: str) -> dict[str, Any]:
    start = time.perf_counter()
    model = create_llm(DEEPSEEK_CONFIG)
    log_dependency(
        "dependency.llm.call_start",
        component="diagnosis_explainer",
        provider=str(DEEPSEEK_CONFIG.provider),
        model_name=DEEPSEEK_CONFIG.model_name,
        purpose="diagnosis_explanation",
        ok=True,
    )
    try:
        response = model.invoke(prompt)
    except Exception as exc:
        log_dependency(
            "dependency.llm.call_error",
            component="diagnosis_explainer",
            provider=str(DEEPSEEK_CONFIG.provider),
            model_name=DEEPSEEK_CONFIG.model_name,
            purpose="diagnosis_explanation",
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            ok=False,
            level="ERROR",
            **exc_meta(exc),
        )
        raise
    log_dependency(
        "dependency.llm.call_ok",
        component="diagnosis_explainer",
        provider=str(DEEPSEEK_CONFIG.provider),
        model_name=DEEPSEEK_CONFIG.model_name,
        purpose="diagnosis_explanation",
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        output_len=len(getattr(response, "content", "") or ""),
        ok=True,
    )
    data = json.loads(_strip_json_fence(response.content))
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object.")
    return data


def explain_benchmark_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""你是 medical-nlp 项目的 benchmark 错误分析助手。
请只基于下面这份 current-run payload 生成“人能看懂”的中文错误分析。
不要读取或假设任何历史运行日志，不要编造 payload 里没有的事实。

主口径：
- overall_success = benchmark_correct AND expansion_success AND standardization_success。
- overall_failure = benchmark_mismatch OR expansion_blocked OR standardization_failure。
- benchmark_mismatch、expansion_blocked、standardization_failure 是可重叠失败标签，不能直接相加。
- record_status_summary 是 record 数，不是 case 数。

扩写失败解释要求：
- 不能只说 NOT_EXPANDED。
- 如果 failure_type = NO_CANDIDATES，必须说明 failure_subtype。
- 必须说明 fallback_called、fallback_candidate_count。
- 如果有 fallback_reason，必须引用。

标准化失败解释要求：
- 如果是扩写失败导致无法标准化，要说明“标准化失败是扩写失败的下游结果”。
- 如果是 WITHHELD，要说明 failure_reason 和 retrieved_top 反映的是“检索到了候选但 verifier 不敢绑定”。

输出 raw JSON，结构必须是：
{{
  "executive_summary": "一段中文总结",
  "key_findings": ["中文要点"],
  "failure_case_notes": [
    {{
      "id": "...",
      "labels": ["benchmark_mismatch"],
      "what_happened": "...",
      "likely_cause": "...",
      "next_step": "..."
    }}
  ],
  "benchmark_mismatch_notes": [
    {{"id": "...", "what_happened": "...", "likely_cause": "...", "next_step": "..."}}
  ],
  "expansion_blocked_notes": [
    {{"id": "...", "what_happened": "...", "likely_cause": "...", "next_step": "..."}}
  ],
  "standardization_failure_notes": [
    {{"id": "...", "what_happened": "...", "likely_cause": "...", "next_step": "..."}}
  ],
  "manual_followups": ["需要人工确认或后续实验的事项"],
  "candidate_gold_case_drafts": []
}}

candidate_gold_case_drafts 默认留空，除非 payload 明确显示 gold 本身疑似错误。

Payload:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""
    return invoke_json_llm(prompt)


def build_single_analysis_payload(text: str, analysis_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": "single user input only",
        "text": text,
        "success": analysis_result.get("success"),
        "expansion_success": analysis_result.get("expansion_success"),
        "standardization_success": analysis_result.get("standardization_success"),
        "success_breakdown": analysis_result.get("success_breakdown") or {},
        "expanded_text": analysis_result.get("expanded_text"),
        "mappings": analysis_result.get("mappings") or [],
        "standardized_entities": analysis_result.get("standardized_entities") or [],
        "mapping_states": analysis_result.get("mapping_states") or [],
    }


def explain_single_analysis(text: str, analysis_result: dict[str, Any]) -> dict[str, Any]:
    payload = build_single_analysis_payload(text, analysis_result)
    prompt = f"""你是 medical-nlp 项目的在线单句诊断助手。
请只解释用户当前输入的一句话，不要使用 benchmark gold，也不要讨论 benchmark accuracy。

你要根据 payload 中的结构化字段，写出可供普通人阅读的中文诊断：
- 哪些缩写被扩写了。
- 哪些 record 是 CODED / WITHHELD / NOT_EXPANDED / ABSTAIN。
- 如果扩写失败，说明 failure_type / failure_subtype / evidence / suggestion。
- 如果标准化失败，说明是否是扩写失败的下游结果，还是 WITHHELD。
- 如果成功，说明为什么可以认为本次链路完成。

输出 raw JSON，结构必须是：
{{
  "summary": "一段中文总结",
  "record_notes": [
    {{
      "abbreviation": "...",
      "status": "...",
      "explanation": "...",
      "suggestion": "..."
    }}
  ],
  "next_steps": ["中文建议"]
}}

Payload:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""
    return invoke_json_llm(prompt)
