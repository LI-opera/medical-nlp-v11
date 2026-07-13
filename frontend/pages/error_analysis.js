import { escapeHtml, percent } from "../utils/format.js";
import { renderFailureTypePie, selectedFailureBucket } from "../components/failure_pie.js";
import { renderFilteredTriage } from "../components/triage_report.js";

export function createErrorAnalysis({ state, fetchJson, frontendLogger, errorType, errorSummary, render }) {
  async function loadErrors({ renderPage = true } = {}) {
    const startedAt = performance.now();
    state.errorsError = "";
    try {
      const [report, triage] = await Promise.all([
        fetchJson("/error-analysis/report"),
        fetchJson("/error-analysis/triage"),
      ]);
      state.errors = report;
      state.triage = triage;
      const summary = report?.overall_failure_analysis || {};
      const failedCases = summary.failure_cases || report?.failed_cases || report?.failure_cases || [];
      frontendLogger.info("ui.errors.load_ok", {
        duration_ms: Math.round(performance.now() - startedAt),
        failed_case_count: failedCases.length,
        triage_exists: Boolean(triage?.exists),
      });
    } catch (error) {
      state.errorsError = error.message;
      frontendLogger.error("ui.errors.load_error", {
        duration_ms: Math.round(performance.now() - startedAt),
        error_type: errorType(error),
        error_summary: errorSummary(error),
      });
    }
    if (renderPage) render();
  }

  function renderErrors() {
    if (state.errorsError) return `<div class="notice">错误分析读取失败：${escapeHtml(state.errorsError)}</div>`;
    if (!state.errors) return `<div class="empty">正在读取 error_analysis_report.json 和 error_triage_report.md...</div>`;
    const summary = state.errors.overall_failure_analysis || {};
    const failedCases = summary.failure_cases || state.errors.failed_cases || state.errors.failure_cases || [];
    return `
      <section class="panel">
        <div class="panel-header"><div><div class="panel-title">Benchmark 失败口径</div><div class="panel-subtitle">基于 error_analysis_report.json；总体失败集合 = benchmark_mismatch ∪ expansion_blocked ∪ standardization_failure。</div></div><button class="btn ghost" id="refreshErrors">刷新</button></div>
        <div class="panel-body"><div class="metric-grid">
          <div class="metric"><div class="metric-label">Overall Success</div><div class="metric-value">${summary.overall_success_count ?? "-"}</div></div>
          <div class="metric"><div class="metric-label">Overall Failure</div><div class="metric-value">${summary.overall_failure_count ?? "-"}</div></div>
          <div class="metric"><div class="metric-label">Success Rate</div><div class="metric-value">${percent(summary.overall_success_rate)}</div></div>
          <div class="metric"><div class="metric-label">Failure Cases</div><div class="metric-value">${failedCases.length}</div></div>
        </div></div>
      </section>
      <div class="grid"><section class="panel"><div class="panel-header"><div><div class="panel-title">失败类型分布</div><div class="panel-subtitle">普通饼图展示各错误类型占比；交集作为独立扇区展示，点击扇区或图例筛选下方解释。</div></div></div><div class="panel-body">${renderFailureTypePie(failedCases, state.selectedErrorSlice)}</div></section></div>
      <section class="panel"><div class="panel-header"><div><div class="panel-title">Benchmark LLM Triage 报告</div><div class="panel-subtitle">只展示 LLM 解释；点击上方错误类型后展示对应 case。</div></div></div><div class="panel-body">${renderFilteredTriage({ triage: state.triage, failedCases, selectedErrorSlice: state.selectedErrorSlice, selectedFailureBucket })}</div></section>
    `;
  }

  return { loadErrors, renderErrors };
}
