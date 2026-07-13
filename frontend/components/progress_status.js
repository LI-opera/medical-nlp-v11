import { escapeHtml, promotionKey } from "../utils/format.js";

export function renderPromotionApplyStatus(state) {
  if (state.applyingPromotions) {
    return `
      <div class="apply-status">
        <div class="apply-status-row"><span>正在写入 primary 缩写词典...</span><strong>${state.promotionApplyProgress}%</strong></div>
        <div class="progress-track"><div class="progress-fill" style="width:${state.promotionApplyProgress}%"></div></div>
      </div>
    `;
  }
  if (state.promotionApplyResult) {
    const appended = state.promotionApplyResult.appended_count ?? 0;
    const skipped = state.promotionApplyResult.skipped_count ?? 0;
    return `
      <div class="apply-status success">
        <div class="checkmark" aria-hidden="true"><svg viewBox="0 0 52 52"><circle cx="26" cy="26" r="24"></circle><path d="M15 27.5 L23 35 L38 18"></path></svg></div>
        <div><div class="apply-success-title">写入完成</div><div class="apply-success-text">新增 ${appended} 个候选，跳过 ${skipped} 个已存在或无效候选。</div></div>
      </div>
    `;
  }
  if (state.promotionApplyError) return `<div class="notice bad-notice">写入失败：${escapeHtml(state.promotionApplyError)}</div>`;
  return `<div class="notice" style="margin-top:14px;">确认后会把未存在的新候选 append 到 backend/data/abbr_candidates.py；同一缩写可保留多个扩写。</div>`;
}

export function renderSinglePromotionStatus(state, item) {
  const key = promotionKey(item);
  const result = state.singlePromotionResults[key];
  const isApplying = state.singlePromotionApplying && state.singlePromotionKey === key;
  if (isApplying) {
    return `<div class="inline-apply-status"><div class="apply-status-row"><span>正在写入 primary...</span><strong>${state.singlePromotionProgress}%</strong></div><div class="progress-track"><div class="progress-fill" style="width:${state.singlePromotionProgress}%"></div></div></div>`;
  }
  if (result) {
    const appended = result.appended_count || 0;
    return `<div class="inline-apply-status success"><span class="mini-check">✓</span><span>${appended ? "已写入 primary" : "该候选已在 primary 中"}</span></div>`;
  }
  if (state.singlePromotionError && state.singlePromotionKey === key) return `<div class="notice bad-notice" style="margin-top:10px;">写入失败：${escapeHtml(state.singlePromotionError)}</div>`;
  return `<div class="single-promotion-hint">该结果来自 fallback 且已 CODED，可沉淀到 primary 候选库。</div>`;
}
