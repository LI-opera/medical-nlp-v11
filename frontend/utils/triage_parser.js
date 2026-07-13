// 只负责解析 triage Markdown，不负责请求和页面状态。
export function extractMarkdownBetween(markdown, startHeading, endHeadingPattern) {
  const start = markdown.indexOf(startHeading);
  if (start < 0) return "";
  const rest = markdown.slice(start);
  const end = rest.search(endHeadingPattern);
  return end > 0 ? rest.slice(0, end).trim() : rest.trim();
}

export function extractCaseMarkdown(markdown, caseIds) {
  const ids = new Set((caseIds || []).filter(Boolean));
  if (!markdown || !ids.size) return "";
  const humanSection = extractMarkdownBetween(markdown, "## 9. 总失败样例的人话解释", /^##\s+10\./m);
  const sections = humanSection.split(/(?=^###\s+)/m);
  const selected = [];
  const seen = new Set();
  sections.forEach((section) => {
    const match = section.match(/^###\s+([^\s]+)/m);
    if (!match || !ids.has(match[1]) || seen.has(match[1])) return;
    seen.add(match[1]);
    selected.push(section.trim());
  });
  return selected.join("\n\n");
}

export function parseTriageCards(markdown) {
  if (!markdown) return [];
  return markdown
    .split(/(?=^###\s+)/m)
    .map((section) => section.trim())
    .filter(Boolean)
    .map((section) => {
      const titleMatch = section.match(/^###\s+(.+)$/m);
      if (!titleMatch) return null;
      const lines = section.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      const card = {
        title: titleMatch[1].trim(),
        labels: "",
        what: "",
        reason: "",
        suggestion: "",
        extra: [],
      };
      let skippingLabelBlock = false;
      lines.slice(1).forEach((line) => {
        const text = line.replace(/^[-*]\s*/, "").trim();
        if (text.startsWith("失败标签:")) {
          skippingLabelBlock = text.includes("[") && !text.includes("]");
          card.labels = text.replace("失败标签:", "").replace(/[\[\]`]/g, "").trim();
        } else if (text.startsWith("发生了什么:") || text.startsWith("情况:")) {
          skippingLabelBlock = false;
          card.what = text.replace(/^(发生了什么|情况):/, "").trim();
        } else if (text.startsWith("可能原因:")) {
          skippingLabelBlock = false;
          card.reason = text.replace("可能原因:", "").trim();
        } else if (text.startsWith("下一步建议:")) {
          skippingLabelBlock = false;
          card.suggestion = text.replace("下一步建议:", "").trim();
        } else if (skippingLabelBlock) {
          if (text.includes("]")) skippingLabelBlock = false;
        } else if (text) {
          card.extra.push(text);
        }
      });
      return card;
    })
    .filter(Boolean);
}
