import { escapeHtml } from "../utils/format.js";
import { extractCaseMarkdown, extractMarkdownBetween, parseTriageCards } from "../utils/triage_parser.js";

export function renderTriageCards(markdown, emptyText) {
  const cards = parseTriageCards(markdown);
  if (!cards.length) return `<div class="empty">${escapeHtml(emptyText || "当前筛选下没有可展示的人话解释。")}</div>`;
  return `
    <div class="triage-card-list">
      ${cards.map((card) => `
        <article class="triage-card">
          <div class="triage-card-head"><div class="triage-case-id">${escapeHtml(card.title)}</div>${card.labels ? `<div class="triage-labels">${escapeHtml(card.labels)}</div>` : ""}</div>
          ${card.what ? `<div class="triage-section"><div class="triage-section-title">情况</div><p>${escapeHtml(card.what)}</p></div>` : ""}
          ${card.reason ? `<div class="triage-section"><div class="triage-section-title">可能原因</div><p>${escapeHtml(card.reason)}</p></div>` : ""}
          ${card.suggestion ? `<div class="triage-section suggestion"><div class="triage-section-title">下一步建议</div><p>${escapeHtml(card.suggestion)}</p></div>` : ""}
          ${card.extra.length ? `<div class="triage-extra">${card.extra.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}</div>` : ""}
        </article>
      `).join("")}
    </div>
  `;
}

export function renderFilteredTriage({ triage, failedCases, selectedErrorSlice, selectedFailureBucket }) {
  if (!triage?.exists) return `<div class="empty">还没有生成 error_triage_report.md。</div>`;
  const bucket = selectedFailureBucket(failedCases, selectedErrorSlice);
  const markdown = triage.markdown || "";
  const caseIds = (bucket?.cases || []).map((item) => item.id || item.case_id).filter(Boolean);
  const body = bucket?.key === "all"
    ? extractMarkdownBetween(markdown, "## 9. 总失败样例的人话解释", /^##\s+10\./m)
    : extractCaseMarkdown(markdown, caseIds);
  return `
    <div class="filter-note">当前筛选：<strong>${escapeHtml(bucket?.label || "全部失败")}</strong>，共 ${bucket?.cases?.length ?? failedCases.length} 个 case。${escapeHtml(bucket?.description || "只展示 LLM 整理后的人话解释，不展示原始 JSON 诊断字段。")}</div>
    ${renderTriageCards(body, `当前报告没有找到这些 case 的人话解释：${caseIds.join(", ")}`)}
  `;
}
