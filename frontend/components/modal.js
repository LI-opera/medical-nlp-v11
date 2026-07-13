import { escapeHtml } from "../utils/format.js";

export function renderPromotionConfirmModal(state) {
  if (!state.promotionConfirmOpen) return "";
  const newCount = state.promotions?.new_item_count || 0;
  const total = state.promotions?.total_items || 0;
  return `
    <div class="modal-backdrop" role="presentation"><div class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="promotionConfirmTitle">
      <div><div class="confirm-title" id="promotionConfirmTitle">确认写入 primary 缩写词典？</div><div class="confirm-text">本次将把 ${newCount} 个新候选 append 到 <strong>backend/data/abbr_candidates.py</strong>。当前候选列表共 ${total} 条，已存在候选会自动跳过。</div></div>
      <div class="confirm-actions"><button class="btn ghost" id="cancelPromotionApply">取消</button><button class="btn primary" id="confirmPromotionApply">确认写入</button></div>
    </div></div>
  `;
}

export function renderSinglePromotionConfirmModal(state) {
  if (!state.singlePromotionConfirmOpen || !state.singlePromotionItem) return "";
  const item = state.singlePromotionItem;
  return `
    <div class="modal-backdrop" role="presentation"><div class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="singlePromotionConfirmTitle">
      <div><div class="confirm-title" id="singlePromotionConfirmTitle">写入当前 fallback 候选？</div><div class="confirm-text">将把 <strong>${escapeHtml(item.abbreviation)}</strong> -> <strong>${escapeHtml(item.expansion)}</strong> append 到 <strong>backend/data/abbr_candidates.py</strong>。如果 primary 中已经存在相同扩写，会自动跳过。</div></div>
      <div class="confirm-actions"><button class="btn ghost" id="cancelSinglePromotion">取消</button><button class="btn primary" id="confirmSinglePromotion">确认写入</button></div>
    </div></div>
  `;
}
