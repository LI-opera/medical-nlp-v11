export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function percent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "0.0%";
  }
  return `${(Number(value) * 100).toFixed(1)}%`;
}

export function statusPill(value, label) {
  const normalized = value === true || value === "ok" || value === "CODED";
  const withheld = value === "WITHHELD";
  const bad = value === false || value === "NOT_EXPANDED" || value === "ABSTAIN";
  const cls = normalized ? "ok" : withheld ? "warn" : bad ? "bad" : "neutral";
  return `<span class="status ${cls}">${escapeHtml(label ?? String(value))}</span>`;
}

export function sourcePill(source) {
  if (!source) return `<span class="status neutral">unknown</span>`;
  const cls = source === "fallback" ? "info" : source === "primary" ? "neutral" : "warn";
  return `<span class="status ${cls}">${escapeHtml(source)}</span>`;
}

export function jsonBlock(data) {
  return `<pre class="json">${escapeHtml(JSON.stringify(data ?? {}, null, 2))}</pre>`;
}

export function mappingSet(mappings) {
  return new Map(
    (mappings || [])
      .filter((item) => item.abbreviation)
      .map((item) => [String(item.abbreviation).toUpperCase(), item])
  );
}

export function explainBenchmarkFailure(caseItem) {
  const expected = mappingSet(caseItem.expected_mappings || []);
  const predicted = mappingSet(caseItem.predicted_mappings || []);
  const expectedKeys = new Set(expected.keys());
  const predictedKeys = new Set(predicted.keys());
  const extra = [...predictedKeys].filter((key) => !expectedKeys.has(key));
  const missing = [...expectedKeys].filter((key) => !predictedKeys.has(key));
  const wrong = [...expectedKeys]
    .filter((key) => predictedKeys.has(key))
    .filter((key) => {
      const exp = String(expected.get(key)?.expansion || "").toLowerCase().trim();
      const pred = String(predicted.get(key)?.expansion || "").toLowerCase().trim();
      return exp && pred && exp !== pred;
    });

  const parts = [];
  if (extra.length) parts.push(`系统额外扩写了 gold 中不要求的缩写：${extra.join(", ")}。`);
  if (missing.length) parts.push(`系统漏掉了 gold 期待扩写的缩写：${missing.join(", ")}。`);
  if (wrong.length) parts.push(`系统扩写结果与 gold 不一致：${wrong.join(", ")}。`);
  if (!parts.length) parts.push("predicted_mappings 与 expected_mappings 不一致。");
  return parts.join("");
}

export function formatMappings(mappings) {
  if (!mappings || !mappings.length) return "[]";
  return mappings.map((item) => `${item.abbreviation} -> ${item.expansion}`).join("; ");
}

export function findStandardizedEntity(result, stateItem) {
  const entities = result?.standardized_entities || [];
  return entities.find((entity) => {
    const sameAbbr = String(entity.abbreviation || "").toUpperCase() === String(stateItem.abbreviation || "").toUpperCase();
    const sameExpansion = String(entity.expansion || "").toLowerCase().trim() === String(stateItem.expansion || "").toLowerCase().trim();
    return sameAbbr && sameExpansion;
  });
}

export function entityToConcept(entity) {
  if (!entity) return null;
  return {
    concept_id: entity.concept_id,
    concept_name: entity.concept_name,
    concept_code: entity.concept_code,
    domain_id: entity.domain_id,
    score: entity.score,
  };
}

export function promotionKey(item) {
  return `${String(item?.abbreviation || "").toUpperCase()}::${String(item?.expansion || "").toLowerCase()}`;
}
