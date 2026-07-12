run_benchmark.py
    执行 benchmark

error_analysis_report.py
    生成结构化错误分析

error_triage.py
    调用 LLM 生成人话错误解释

collect_fallback_candidate_promotions.py
    提取可沉淀的 fallback 候选

apply_fallback_candidate_promotions.py
    将人工确认后的候选写入 primary

archive/
    历史评估结果

runtime/
    当前运行结果，不提交 Git