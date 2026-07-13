import {
  entityToConcept,
  escapeHtml,
  findStandardizedEntity,
  jsonBlock,
  promotionKey,
  sourcePill,
  statusPill,
} from "../utils/format.js";
import { renderSinglePromotionStatus } from "../components/progress_status.js";

// Analyze 页面的异步动作与 HTML 渲染。这里不负责路由，只消费 app.js 注入的共享状态。
export function createAnalyzeActions({
  state,
  fetchJson,
  frontendLogger,
  safeTextMeta,
  safeResponseSize,
  errorType,
  errorSummary,
  render,
}) {
  async function runAnalyze() {
    const startedAt = performance.now();
    frontendLogger.info("ui.analyze.click", safeTextMeta(state.text));
    state.analyzing = true;
    state.analyzeError = "";
    state.analyzeResult = null;
    state.diagnosis = null;
    state.diagnosisError = "";
    render();

    try {
      state.analyzeResult = await fetchJson("/expand/simple", {
        method: "POST",
        body: JSON.stringify({ text: state.text }),
      });
      frontendLogger.info("ui.analyze.result_ok", {
        ...safeTextMeta(state.text),
        duration_ms: Math.round(performance.now() - startedAt),
        backend_request_id: state.analyzeResult?.request_id || null,
        success: Boolean(state.analyzeResult?.success),
        expansion_success: Boolean(state.analyzeResult?.expansion_success),
        standardization_success: Boolean(state.analyzeResult?.standardization_success),
        mapping_count: (state.analyzeResult?.mappings || []).length,
        mapping_state_count: (state.analyzeResult?.mapping_states || []).length,
      });
    } catch (error) {
      state.analyzeError = error.message;
      frontendLogger.error("ui.analyze.result_error", {
        ...safeTextMeta(state.text),
        duration_ms: Math.round(performance.now() - startedAt),
        error_type: errorType(error),
        error_summary: errorSummary(error),
      });
    } finally {
      state.analyzing = false;
      render();
    }
  }

  async function runDiagnosis() {
    if (!state.analyzeResult) return;
    const startedAt = performance.now();
    frontendLogger.info("ui.diagnosis.click", {
      ...safeTextMeta(state.text),
      mapping_state_count: (state.analyzeResult?.mapping_states || []).length,
    });
    state.diagnosing = true;
    state.diagnosisError = "";
    state.diagnosis = null;
    render();

    try {
      state.diagnosis = await fetchJson("/analysis/diagnose", {
        method: "POST",
        body: JSON.stringify({
          text: state.text,
          analysis_result: state.analyzeResult,
        }),
      });
      frontendLogger.info("ui.diagnosis.result_ok", {
        duration_ms: Math.round(performance.now() - startedAt),
        response_size: safeResponseSize(state.diagnosis),
      });
    } catch (error) {
      state.diagnosisError = error.message;
      frontendLogger.error("ui.diagnosis.result_error", {
        duration_ms: Math.round(performance.now() - startedAt),
        error_type: errorType(error),
        error_summary: errorSummary(error),
      });
    } finally {
      state.diagnosing = false;
      render();
    }
  }

  return { runAnalyze, runDiagnosis };
}

function buildSinglePromotionItem(state, stateItem, concept) {
  const abbreviation = String(stateItem?.abbreviation || "").trim().toUpperCase();
  const expansion = String(stateItem?.expansion || "").trim();
  const domain = stateItem?.domain || stateItem?.label || concept?.domain_id || "Unknown";
  if (!abbreviation || !expansion) return null;
  return {
    abbreviation,
    expansion,
    domain,
    support_count: 1,
    case_ids: ["single_analyze"],
    examples: [
      {
        id: "single_analyze",
        text: state.text,
        final_expanded_text: state.analyzeResult?.expanded_text || "",
      },
    ],
    chosen_concepts: concept ? [
      {
        concept_id: concept.concept_id,
        concept_name: concept.concept_name,
        domain_id: concept.domain_id,
        concept_code: concept.concept_code,
      },
    ] : [],
    candidate_to_append: {
      expansion,
      domain,
    },
  };
}

function canPromoteSingleCandidate(stateItem, concept) {
  return (
    stateItem?.source === "fallback"
    && stateItem?.status === "CODED"
    && Boolean(stateItem?.abbreviation)
    && Boolean(stateItem?.expansion)
    && Boolean(concept)
  );
}

export function createAnalyzeRenderer({ state, samples }) {
  function renderConceptSummary(concept) {
    if (!concept) return "";
    return `
      <div class="concept-summary">
        <div>
          <span class="diag-label">standard concept</span>
          <strong>${escapeHtml(concept.concept_name || "-")}</strong>
        </div>
        <div>
          <span class="diag-label">concept_id / code</span>
          ${escapeHtml(concept.concept_id || "-")} / ${escapeHtml(concept.concept_code || "-")}
        </div>
        <div>
          <span class="diag-label">concept domain</span>
          ${escapeHtml(concept.domain_id || "-")}
        </div>
        <div>
          <span class="diag-label">score</span>
          ${escapeHtml(concept.score ?? "-")}
        </div>
      </div>
    `;
  }

  function renderSingleDiagnosis() {
    const result = state.analyzeResult;
    if (!result) return `<div class="empty">还没有当前输入的分析结果。</div>`;

    const states = result.mapping_states || [];
    const structured = states.length
      ? `<div class="case-list">${states.map((item) => {
          const failure = item.failure || {};
          const coverage = item.coverage || {};
          const matchedEntity = findStandardizedEntity(result, item);
          const concept = item.chosen_concept || entityToConcept(matchedEntity);
          const promotionItem = canPromoteSingleCandidate(item, concept)
            ? buildSinglePromotionItem(state, item, concept)
            : null;
          const pKey = promotionItem ? promotionKey(promotionItem) : "";
          const promotionDone = Boolean(pKey && state.singlePromotionResults[pKey]);
          const promotionBusy = Boolean(state.singlePromotionApplying && state.singlePromotionKey === pKey);
          const encodedPromotion = promotionItem
            ? encodeURIComponent(JSON.stringify(promotionItem))
            : "";
          return `
            <div class="case-item">
              <div class="case-title">
                <span class="entity-title-main">
                  <span>${escapeHtml(item.abbreviation || "-")}</span>
                  <span class="entity-expansion-label">Expansion:</span>
                  <span class="entity-expansion-text">${escapeHtml(item.expansion || "no expansion")}</span>
                </span>
                <span class="title-actions">
                  ${statusPill(item.status || "unknown", item.status || "unknown")}
                </span>
              </div>
              <div class="diagnosis-grid">
                <div><span class="diag-label">source</span>${sourcePill(item.source)}</div>
                <div><span class="diag-label">coverage</span>${statusPill(Boolean(coverage.coverage_ok), coverage.coverage_ok ? "ok" : "not ok")}</div>
                <div><span class="diag-label">failure_type</span><span class="status neutral">${escapeHtml(failure.type || "-")}</span></div>
                <div><span class="diag-label">failure_subtype</span><span class="status neutral">${escapeHtml(failure.subtype || "-")}</span></div>
                ${promotionItem ? `
                  <div class="diagnosis-action-cell">
                    <button class="btn promote-primary" data-single-promote="${encodedPromotion}" ${promotionDone || promotionBusy ? "disabled" : ""}>${promotionDone ? "已处理" : promotionBusy ? "写入中" : "写入 primary"}</button>
                  </div>
                ` : ""}
              </div>
              ${renderConceptSummary(concept)}
            ${promotionItem ? renderSinglePromotionStatus(state, promotionItem) : ""}
              ${failure.reason ? `<div class="failure-reason">${escapeHtml(failure.reason)}</div>` : ""}
              ${failure.suggestion ? `<div class="notice" style="margin-top:10px;">${escapeHtml(failure.suggestion)}</div>` : ""}
            </div>
          `;
        }).join("")}</div>`
      : `
        <div class="empty">
          <strong>未检测到需要扩写的目标缩写。</strong>
          <div class="empty-detail">当前链路只处理医学缩写扩写与标准化；普通文本、已经写全的医学术语，或未被规则识别为目标缩写的内容，都会保持原文返回。</div>
        </div>
      `;

    const llm = state.diagnosis
      ? `
        <div class="diagnosis-llm">
          <div class="panel-title">LLM解释</div>
          <p>${escapeHtml(state.diagnosis.summary || "")}</p>
          ${(state.diagnosis.record_notes || []).map((note) => `
            <div class="case-item">
              <div class="case-title">
                <span>${escapeHtml(note.abbreviation || "-")}</span>
                ${statusPill(note.status || "unknown", note.status || "unknown")}
              </div>
              <div class="case-text">${escapeHtml(note.explanation || "")}</div>
              ${note.suggestion ? `<div class="notice" style="margin-top:10px;">${escapeHtml(note.suggestion)}</div>` : ""}
            </div>
          `).join("")}
          ${(state.diagnosis.next_steps || []).length ? `
            <div class="notice" style="margin-top:12px;">
              ${(state.diagnosis.next_steps || []).map((item) => `<div>${escapeHtml(item)}</div>`).join("")}
            </div>
          ` : ""}
        </div>
      `
      : "";

    return `
      ${state.diagnosisError ? `<div class="notice" style="margin-bottom:12px;">LLM 诊断失败：${escapeHtml(state.diagnosisError)}</div>` : ""}
      ${structured}
      ${llm}
    `;
  }

  function renderRawJsonDisclosure(result) {
    if (!result) return "";
    return `
      <section class="panel">
        <details class="raw-details">
          <summary>Raw JSON</summary>
          <div class="raw-body">
            ${jsonBlock(result)}
          </div>
        </details>
      </section>
    `;
  }

  function renderAnalyze() {
    const result = state.analyzeResult;

    return `
      <div class="analyze-page">
      <section class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-title">输入文本</div>
            <div class="panel-subtitle">第一版调用 /expand/simple，适合先看链路效果。</div>
          </div>
        </div>
        <div class="panel-body">
          <textarea class="textarea" id="inputText">${escapeHtml(state.text)}</textarea>
          <div class="actions">
            <button class="btn primary" id="runAnalyze" ${state.analyzing ? "disabled" : ""}>
              ${state.analyzing ? "分析中..." : "分析"}
            </button>
            <button class="btn ghost" id="clearText">清空</button>
          </div>
          <div class="samples">
            ${samples.map((sample, index) => `
              <button class="sample" data-sample="${index}">${escapeHtml(sample)}</button>
            `).join("")}
          </div>
          ${state.analyzeError ? `<div class="notice" style="margin-top:14px;">分析失败：${escapeHtml(state.analyzeError)}</div>` : ""}
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-title">扩写文本</div>
            <div class="panel-subtitle">这里展示确定性替换后的最终文本。</div>
          </div>
        </div>
        <div class="panel-body">
          <div class="result-text ${result?.expanded_text ? "" : "result-placeholder"}">${escapeHtml(result?.expanded_text || "暂无结果")}</div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-title">当前单句诊断</div>
            <div class="panel-subtitle">基于本次分析返回的 mapping_states / failure_type / suggestion。</div>
          </div>
          ${result ? `<button class="btn ghost" id="runDiagnosis" ${state.diagnosing ? "disabled" : ""}>${state.diagnosing ? "生成中..." : "生成 LLM 诊断"}</button>` : ""}
        </div>
        <div class="panel-body">
          ${renderSingleDiagnosis()}
        </div>
      </section>

      ${renderRawJsonDisclosure(result)}
      </div>
    `;
  }

  return { renderAnalyze };
}
