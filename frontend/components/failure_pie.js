import { escapeHtml, percent } from "../utils/format.js";

function failureCaseLabels(item) {
  const labels = item?.labels || {};
  const list = item?.failure_labels || [];
  return {
    benchmark_mismatch: Boolean(labels.benchmark_mismatch || list.includes("benchmark_mismatch")),
    expansion_blocked: Boolean(labels.expansion_blocked || list.includes("expansion_blocked")),
    standardization_failure: Boolean(labels.standardization_failure || list.includes("standardization_failure")),
  };
}

function classifyFailureCase(item) {
  const labels = failureCaseLabels(item);
  if (labels.benchmark_mismatch && labels.expansion_blocked) return "benchmark_expansion";
  if (labels.benchmark_mismatch && labels.standardization_failure) return "benchmark_standardization";
  if (labels.benchmark_mismatch) return "benchmark_only";
  if (labels.expansion_blocked) return "expansion_blocked";
  if (labels.standardization_failure) return "standardization_only";
  return "other_failure";
}

function bucketDefinition(key) {
  return {
    benchmark_standardization: ["benchmark + 标准化", "#59aaf5", "既被 benchmark 判错，也存在标准化失败。"],
    expansion_blocked: ["扩写阻断", "#41c7c7", "没有拿到可用扩写，标准化失败是下游结果。"],
    standardization_only: ["仅标准化", "#4fc96f", "扩写存在，但标准化没有成功落到可信概念。"],
    benchmark_only: ["仅 benchmark", "#ffd23c", "只是不符合 gold/benchmark 期望，扩写和标准化本身没有失败。"],
    benchmark_expansion: ["benchmark + 扩写", "#a855f7", "既被 benchmark 判错，也存在扩写阻断。"],
    other_failure: ["其他失败", "#64748b", "未落入主要标签组合的失败。"],
  }[key] || [key, "#64748b", ""];
}

function buildFailureBuckets(cases) {
  const byKey = new Map();
  ["benchmark_standardization", "expansion_blocked", "standardization_only", "benchmark_only", "benchmark_expansion", "other_failure"]
    .forEach((key) => byKey.set(key, []));
  (cases || []).forEach((item) => byKey.get(classifyFailureCase(item))?.push(item));
  return ["benchmark_only", "expansion_blocked", "standardization_only", "benchmark_standardization", "benchmark_expansion", "other_failure"]
    .map((key) => {
      const [label, color, description] = bucketDefinition(key);
      return { key, label, color, description, cases: byKey.get(key) || [] };
    })
    .filter((bucket) => bucket.cases.length > 0);
}

function polarPoint(angle, radius, center = 110) {
  const radians = (angle * Math.PI) / 180;
  return { x: center + radius * Math.cos(radians), y: center + radius * Math.sin(radians) };
}

function pieSlicePath(startPercent, endPercent, radius = 100, centerX = 300, centerY = 150) {
  const startAngle = startPercent * 3.6 - 90;
  const endAngle = endPercent * 3.6 - 90;
  const outerStart = polarPoint(startAngle, radius, centerX);
  const outerEnd = polarPoint(endAngle, radius, centerX);
  outerStart.y += centerY - centerX;
  outerEnd.y += centerY - centerX;
  const largeArc = endPercent - startPercent > 50 ? 1 : 0;
  return `M ${centerX} ${centerY} L ${outerStart.x.toFixed(3)} ${outerStart.y.toFixed(3)} A ${radius} ${radius} 0 ${largeArc} 1 ${outerEnd.x.toFixed(3)} ${outerEnd.y.toFixed(3)} Z`;
}

export function renderFailureTypePie(failedCases, selectedErrorSlice = "all") {
  const total = (failedCases || []).length;
  if (!total) return `<div class="empty">暂无失败 case，无法生成错误类型分布。</div>`;
  const buckets = buildFailureBuckets(failedCases);
  const selected = buckets.some((bucket) => bucket.key === selectedErrorSlice) ? selectedErrorSlice : "all";
  let cursor = 0;
  const slices = buckets.map((bucket) => {
    const start = cursor;
    const size = (bucket.cases.length / total) * 100;
    cursor += size;
    return { ...bucket, start, end: cursor };
  });

  return `
    <div class="simple-pie-wrap">
      <svg class="simple-pie-svg" viewBox="0 0 680 330" role="img" aria-label="失败类型分布">
        ${slices.map((slice) => {
          const mid = (slice.start + slice.end) / 2;
          const angle = mid * 3.6 - 90;
          const edge = polarPoint(angle, 102, 300);
          edge.y += 150 - 300;
          const elbow = polarPoint(angle, 128, 300);
          elbow.y += 150 - 300;
          const rightSide = Math.cos((angle * Math.PI) / 180) >= 0;
          const labelX = elbow.x + (rightSide ? 34 : -34);
          const labelY = elbow.y;
          const anchor = rightSide ? "start" : "end";
          return `
            <path class="pie-slice ${selected === slice.key ? "active" : ""}" data-error-slice="${slice.key}" d="${pieSlicePath(slice.start, slice.end)}" fill="${slice.color}">
              <title>${escapeHtml(slice.label)} ${slice.cases.length} (${percent(slice.cases.length / total)})</title>
            </path>
            <path class="pie-leader" d="M ${edge.x.toFixed(1)} ${edge.y.toFixed(1)} Q ${elbow.x.toFixed(1)} ${elbow.y.toFixed(1)} ${labelX.toFixed(1)} ${labelY.toFixed(1)}" stroke="${slice.color}"></path>
            <text class="pie-label" x="${labelX.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="${anchor}">${escapeHtml(slice.label)}: ${percent(slice.cases.length / total)}</text>
          `;
        }).join("")}
      </svg>
      <div class="pie-bottom-legend">
        <button class="pie-legend-item ${selected === "all" ? "active" : ""}" data-error-slice="all"><span class="legend-dot" style="background:#111827"></span><span>全部失败</span></button>
        ${slices.map((slice) => `<button class="pie-legend-item ${selected === slice.key ? "active" : ""}" data-error-slice="${slice.key}"><span class="legend-dot" style="background:${slice.color}"></span><span>${escapeHtml(slice.label)}</span></button>`).join("")}
      </div>
    </div>
  `;
}

export function selectedFailureBucket(failedCases, selectedErrorSlice = "all") {
  if (selectedErrorSlice === "all") return { key: "all", label: "全部失败", description: "显示本轮错误分析报告的全部内容。", cases: failedCases || [] };
  return buildFailureBuckets(failedCases).find((bucket) => bucket.key === selectedErrorSlice) || null;
}
