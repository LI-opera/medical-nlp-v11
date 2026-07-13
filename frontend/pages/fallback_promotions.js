import { escapeHtml, promotionKey, statusPill } from "../utils/format.js";
import { renderPromotionApplyStatus } from "../components/progress_status.js";

// Fallback Promotions 页面模块：候选加载、批量/单条写入和页面展示。
export function createFallbackPromotions({ state, fetchJson, frontendLogger, errorType, errorSummary, hashText, render }) {
  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function loadPromotions({ renderPage = true } = {}) {
    const startedAt = performance.now();
    state.promotionsError = "";
    try {
      state.promotions = await fetchJson("/candidate-promotions");
      frontendLogger.info("ui.promotions.load_ok", {
        duration_ms: Math.round(performance.now() - startedAt),
        total_items: state.promotions?.total_items,
        new_item_count: state.promotions?.new_item_count,
        already_exists_count: state.promotions?.already_exists_count,
      });
    } catch (error) {
      state.promotionsError = error.message;
      frontendLogger.error("ui.promotions.load_error", { duration_ms: Math.round(performance.now() - startedAt), error_type: errorType(error), error_summary: errorSummary(error) });
    }
    if (renderPage) render();
  }

  async function applyPromotions() {
    if (state.applyingPromotions) return;
    const items = state.promotions?.items || [];
    const newCount = state.promotions?.new_item_count || 0;
    if (!items.length || !newCount) return;
    const startedAt = performance.now();
    frontendLogger.info("ui.promotions.apply_confirm", { total_items: state.promotions?.total_items, new_item_count: newCount, already_exists_count: state.promotions?.already_exists_count });
    state.promotionConfirmOpen = false;
    state.applyingPromotions = true;
    state.promotionApplyProgress = 8;
    state.promotionApplyResult = null;
    state.promotionApplyError = "";
    render();
    const timer = window.setInterval(() => {
      if (!state.applyingPromotions) return window.clearInterval(timer);
      state.promotionApplyProgress = Math.min(88, state.promotionApplyProgress + 8);
      render();
    }, 160);
    try {
      const result = await fetchJson("/candidate-promotions/apply", { method: "POST" });
      window.clearInterval(timer);
      state.promotionApplyProgress = 100;
      state.promotionApplyResult = result;
      state.applyingPromotions = false;
      frontendLogger.info("ui.promotions.apply_ok", { duration_ms: Math.round(performance.now() - startedAt), appended_count: result?.appended_count, skipped_count: result?.skipped_count });
      await loadPromotions();
      state.promotionApplyProgress = 100;
      state.promotionApplyResult = result;
    } catch (error) {
      window.clearInterval(timer);
      state.applyingPromotions = false;
      state.promotionApplyError = error.message;
      frontendLogger.error("ui.promotions.apply_error", { duration_ms: Math.round(performance.now() - startedAt), error_type: errorType(error), error_summary: errorSummary(error) });
    } finally {
      render();
    }
  }

  async function applySinglePromotion() {
    if (state.singlePromotionApplying || !state.singlePromotionItem) return;
    const startedAt = performance.now();
    const item = state.singlePromotionItem;
    frontendLogger.info("ui.promotions.apply_single_confirm", { abbreviation: item.abbreviation, expansion_hash: hashText(item.expansion), domain: item.domain });
    state.singlePromotionConfirmOpen = false;
    state.singlePromotionApplying = true;
    state.singlePromotionProgress = 10;
    state.singlePromotionError = "";
    render();
    const timer = window.setInterval(() => {
      if (!state.singlePromotionApplying) return window.clearInterval(timer);
      state.singlePromotionProgress = Math.min(88, state.singlePromotionProgress + 10);
      render();
    }, 140);
    try {
      const result = await fetchJson("/candidate-promotions/apply-single", { method: "POST", body: JSON.stringify(item) });
      window.clearInterval(timer);
      state.singlePromotionProgress = 100;
      state.singlePromotionResults = { ...state.singlePromotionResults, [state.singlePromotionKey]: result };
      state.singlePromotionApplying = false;
      frontendLogger.info("ui.promotions.apply_single_ok", { duration_ms: Math.round(performance.now() - startedAt), abbreviation: item.abbreviation, expansion_hash: hashText(item.expansion), domain: item.domain, appended_count: result?.appended_count, skipped_count: result?.skipped_count });
    } catch (error) {
      window.clearInterval(timer);
      state.singlePromotionApplying = false;
      state.singlePromotionError = error.message;
      frontendLogger.error("ui.promotions.apply_single_error", { duration_ms: Math.round(performance.now() - startedAt), abbreviation: item.abbreviation, expansion_hash: hashText(item.expansion), domain: item.domain, error_type: errorType(error), error_summary: errorSummary(error) });
    } finally {
      render();
    }
  }

  function table(headers, rows) {
    return `<div class="table-wrap"><table><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function renderPromotions() {
    if (state.promotionsError) return `<div class="notice">候选沉淀读取失败：${escapeHtml(state.promotionsError)}</div>`;
    if (!state.promotions) return `<div class="empty">正在读取 fallback_candidate_promotions.json...</div>`;
    const items = state.promotions.items || [];
    const canApply = Boolean(items.length && (state.promotions.new_item_count || 0));
    return `
      <section class="panel"><div class="panel-header"><div><div class="panel-title">Benchmark fallback 候选沉淀概览</div><div class="panel-subtitle">基于 benchmark 中 fallback 成功且 CODED 的案例；人工确认后写入 primary。</div></div><div class="actions inline"><button class="btn ghost" id="refreshPromotions" ${state.applyingPromotions ? "disabled" : ""}>刷新</button><button class="btn primary" id="applyPromotions" ${!canApply || state.applyingPromotions ? "disabled" : ""}>${state.applyingPromotions ? "写入中..." : "确认写入 primary"}</button></div></div>
        <div class="panel-body"><div class="metric-grid"><div class="metric"><div class="metric-label">Total Items</div><div class="metric-value">${state.promotions.total_items || 0}</div></div><div class="metric"><div class="metric-label">New Items</div><div class="metric-value">${state.promotions.new_item_count || 0}</div></div><div class="metric"><div class="metric-label">Already Exists</div><div class="metric-value">${state.promotions.already_exists_count || 0}</div></div></div>${renderPromotionApplyStatus(state)}</div>
      </section>
      <section class="panel"><div class="panel-header"><div><div class="panel-title">候选列表</div><div class="panel-subtitle">同一缩写允许多个扩写，写入 primary 时应 append 到 list。</div></div></div><div class="panel-body">${items.length ? table(["缩写", "扩写", "Domain", "Support", "Case IDs", "状态"], items.map((item) => [escapeHtml(item.abbreviation), escapeHtml(item.expansion), escapeHtml(item.domain), escapeHtml(item.support_count), escapeHtml((item.case_ids || []).join(", ")), item.already_exists ? statusPill("warn", "exists") : statusPill("ok", "new")])) : `<div class="empty">没有可沉淀候选。</div>`}</div></section>
    `;
  }

  return { loadPromotions, applyPromotions, applySinglePromotion, renderPromotions };
}
