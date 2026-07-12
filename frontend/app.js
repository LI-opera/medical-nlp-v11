const routes = {
  analyze: {
    title: "缩写标准化工作台",
    kicker: "输入临床文本，查看扩写、标准化和成功状态。",
  },
  benchmarkOverview: {
    title: "Benchmark Overview",
    kicker: "查看 benchmark 准确率、分类占比和失败案例。",
  },
  benchmarkErrors: {
    title: "Benchmark Error Analysis",
    kicker: "读取 error_analysis_report 与 triage markdown，集中看 benchmark 失败原因。",
  },
  benchmarkPromotions: {
    title: "Benchmark Fallback Promotions",
    kicker: "查看从 benchmark fallback 成功案例中沉淀出的候选词组。",
  },
};

const samples = [
  "The patient has SOB and CP.",
  "The patient has RA with joint pain and morning stiffness.",
  "The ABG revealed respiratory acidosis with hypoxemia.",
  "The patient has XYZ.",
  "The patient has ABC and SOB.",
];

// 前端与 FastAPI 同源部署时，直接使用当前页面来源，避免用户手动配置端口。
const defaultApiBase = window.location.origin && window.location.origin !== "null"
  ? window.location.origin
  : "http://127.0.0.1:8000";

const state = {
  route: "analyze",
  tab: "mappings",
  text: "",
  apiBase: defaultApiBase,
  health: null,
  healthError: "",
  analyzing: false,
  analyzeResult: null,
  analyzeError: "",
  diagnosing: false,
  diagnosis: null,
  diagnosisError: "",
  benchmark: null,
  benchmarkError: "",
  benchmarkUploading: false,
  benchmarkUploadProgress: 0,
  benchmarkUploadJob: null,
  benchmarkUploadResult: null,
  benchmarkUploadError: "",
  errors: null,
  triage: null,
  errorsError: "",
  selectedErrorSlice: "all",
  promotions: null,
  promotionsError: "",
  applyingPromotions: false,
  promotionApplyProgress: 0,
  promotionApplyResult: null,
  promotionApplyError: "",
  promotionConfirmOpen: false,
  singlePromotionConfirmOpen: false,
  singlePromotionItem: null,
  singlePromotionKey: "",
  singlePromotionApplying: false,
  singlePromotionProgress: 0,
  singlePromotionResults: {},
  singlePromotionError: "",
};

const app = document.getElementById("app");

const frontendLogger = window.frontendLogger;
const {
  randomId,
  hashText,
  truncate,
  errorType,
  errorSummary,
  safeResponseSize,
  safeTextMeta,
} = window.frontendLogUtils;

frontendLogger.setContextProvider(() => ({
  route: state.route,
  apiBase: state.apiBase,
}));

function apiUrl(path) {
  const base = state.apiBase.replace(/\/$/, "");
  return `${base}${path}`;
}

async function fetchJson(path, options = {}) {
  const startedAt = performance.now();
  const frontendRequestId = randomId("fe_req");
  const method = options.method || "GET";
  frontendLogger.info("api.request_start", {
    path,
    method,
    frontend_request_id: frontendRequestId,
  });

  try {
    const response = await fetch(apiUrl(path), {
      headers: {
        "Content-Type": "application/json",
        "X-Frontend-Request-Id": frontendRequestId,
        ...(options.headers || {}),
      },
      ...options,
    });

    if (!response.ok) {
      const text = await response.text();
      const error = new Error(`${response.status} ${response.statusText}: ${text.slice(0, 160)}`);
      frontendLogger.error("api.request_error", {
        path,
        method,
        status: response.status,
        status_text: response.statusText,
        duration_ms: Math.round(performance.now() - startedAt),
        frontend_request_id: frontendRequestId,
        error_type: errorType(error),
        error_summary: `${response.status} ${response.statusText}`,
      });
      throw error;
    }

    const data = await response.json();
    frontendLogger.info("api.request_ok", {
      path,
      method,
      status: response.status,
      status_text: response.statusText,
      duration_ms: Math.round(performance.now() - startedAt),
      frontend_request_id: frontendRequestId,
      backend_request_id: data?.request_id || null,
      response_size: safeResponseSize(data),
    });
    return data;
  } catch (error) {
    if (!(error instanceof Error && /^\d{3}\s/.test(error.message))) {
      frontendLogger.error("api.request_error", {
        path,
        method,
        duration_ms: Math.round(performance.now() - startedAt),
        frontend_request_id: frontendRequestId,
        error_type: errorType(error),
        error_summary: errorSummary(error),
      });
    }
    throw error;
  }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function percent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "0.0%";
  }
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function statusPill(value, label) {
  const normalized = value === true || value === "ok" || value === "CODED";
  const withheld = value === "WITHHELD";
  const bad = value === false || value === "NOT_EXPANDED" || value === "ABSTAIN";
  const cls = normalized ? "ok" : withheld ? "warn" : bad ? "bad" : "neutral";
  return `<span class="status ${cls}">${escapeHtml(label ?? String(value))}</span>`;
}

function sourcePill(source) {
  if (!source) return `<span class="status neutral">unknown</span>`;
  const cls = source === "fallback" ? "info" : source === "primary" ? "neutral" : "warn";
  return `<span class="status ${cls}">${escapeHtml(source)}</span>`;
}

function jsonBlock(data) {
  return `<pre class="json">${escapeHtml(JSON.stringify(data ?? {}, null, 2))}</pre>`;
}

function mappingSet(mappings) {
  return new Map(
    (mappings || [])
      .filter((item) => item.abbreviation)
      .map((item) => [String(item.abbreviation).toUpperCase(), item])
  );
}

function explainBenchmarkFailure(caseItem) {
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

function formatMappings(mappings) {
  if (!mappings || !mappings.length) return "[]";
  return mappings
    .map((item) => `${item.abbreviation} -> ${item.expansion}`)
    .join("; ");
}

function findStandardizedEntity(result, stateItem) {
  const entities = result?.standardized_entities || [];
  return entities.find((entity) => {
    const sameAbbr = String(entity.abbreviation || "").toUpperCase() === String(stateItem.abbreviation || "").toUpperCase();
    const sameExpansion = String(entity.expansion || "").toLowerCase().trim() === String(stateItem.expansion || "").toLowerCase().trim();
    return sameAbbr && sameExpansion;
  });
}

function entityToConcept(entity) {
  if (!entity) return null;
  return {
    concept_id: entity.concept_id,
    concept_name: entity.concept_name,
    concept_code: entity.concept_code,
    domain_id: entity.domain_id,
    score: entity.score,
  };
}

function promotionKey(item) {
  return `${String(item?.abbreviation || "").toUpperCase()}::${String(item?.expansion || "").toLowerCase()}`;
}

function buildSinglePromotionItem(stateItem, concept) {
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

function setRoute(route) {
  frontendLogger.info("ui.route.change", {
    from_route: state.route,
    to_route: route,
  });
  state.route = route;
  state.tab = "mappings";
  render();
  loadRouteData(route);
}

function setApiBase(value) {
  state.apiBase = value.trim() || "http://127.0.0.1:8000";
  localStorage.setItem("medicalNlpApiBase", state.apiBase);
  frontendLogger.info("ui.api_base.save", {
    api_base: state.apiBase,
  });
}

async function checkHealth() {
  const startedAt = performance.now();
  state.healthError = "";
  frontendLogger.info("ui.health.check_start");
  try {
    state.health = await fetchJson("/health");
    frontendLogger.info("ui.health.check_ok", {
      duration_ms: Math.round(performance.now() - startedAt),
    });
  } catch (error) {
    state.health = null;
    state.healthError = error.message;
    frontendLogger.error("ui.health.check_error", {
      duration_ms: Math.round(performance.now() - startedAt),
      error_type: errorType(error),
      error_summary: errorSummary(error),
    });
  }
  render();
}

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

async function loadBenchmark() {
  const startedAt = performance.now();
  state.benchmarkError = "";
  try {
    state.benchmark = await fetchJson("/benchmark/results");
    frontendLogger.info("ui.benchmark.load_ok", {
      duration_ms: Math.round(performance.now() - startedAt),
      total: state.benchmark?.total,
      correct: state.benchmark?.correct,
      accuracy: state.benchmark?.accuracy,
    });
  } catch (error) {
    state.benchmarkError = error.message;
    frontendLogger.error("ui.benchmark.load_error", {
      duration_ms: Math.round(performance.now() - startedAt),
      error_type: errorType(error),
      error_summary: errorSummary(error),
    });
  }
  render();
}

async function uploadBenchmarkFile(file) {
  if (!file || state.benchmarkUploading) return;

  const startedAt = performance.now();
  frontendLogger.info("ui.benchmark.upload_click", {
    file_name: file.name,
    file_size: file.size,
  });
  state.benchmarkUploading = true;
  state.benchmarkUploadProgress = 1;
  state.benchmarkUploadJob = {
    status: "reading",
    stage: "reading_file",
    message: "正在读取上传文件",
    progress: 1,
  };
  state.benchmarkUploadResult = null;
  state.benchmarkUploadError = "";
  render();

  try {
    const text = await file.text();
    frontendLogger.info("ui.benchmark.file_read_ok", {
      file_name: file.name,
      file_size: file.size,
    });

    let payload;
    try {
      payload = JSON.parse(text);
    } catch (error) {
      frontendLogger.error("ui.benchmark.file_parse_error", {
        file_name: file.name,
        file_size: file.size,
        error_type: errorType(error),
        error_summary: errorSummary(error),
      });
      throw error;
    }

    const caseCount = Array.isArray(payload?.cases) ? payload.cases.length : null;
    const job = await fetchJson("/benchmark/cases/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    frontendLogger.info("ui.benchmark.job_create_ok", {
      file_name: file.name,
      file_size: file.size,
      case_count: caseCount,
      job_id: job.id,
      stage: job.stage,
      progress: Number(job.progress || 0),
    });

    state.benchmarkUploadJob = job;
    state.benchmarkUploadProgress = Number(job.progress || 2);
    render();

    let latest = job;
    let lastLoggedStage = latest.stage || latest.status || "";
    let lastLoggedProgressBucket = Math.floor(Number(latest.progress || 0) / 10);
    while (latest.status !== "completed" && latest.status !== "failed") {
      await sleep(1000);
      latest = await fetchJson(`/benchmark/cases/jobs/${encodeURIComponent(job.id)}`);
      state.benchmarkUploadJob = latest;
      state.benchmarkUploadProgress = Number(latest.progress || state.benchmarkUploadProgress || 0);
      const currentStage = latest.stage || latest.status || "";
      const currentProgressBucket = Math.floor(Number(latest.progress || 0) / 10);
      if (currentStage !== lastLoggedStage || currentProgressBucket > lastLoggedProgressBucket) {
        frontendLogger.info("ui.benchmark.job_poll", {
          job_id: job.id,
          stage: latest.stage,
          status: latest.status,
          progress: Number(latest.progress || 0),
          current: latest.current,
          total: latest.total,
        });
        lastLoggedStage = currentStage;
        lastLoggedProgressBucket = currentProgressBucket;
      }
      render();
    }

    if (latest.status === "failed") {
      frontendLogger.error("ui.benchmark.job_failed", {
        job_id: job.id,
        stage: latest.stage,
        status: latest.status,
        progress: Number(latest.progress || 0),
        duration_ms: Math.round(performance.now() - startedAt),
        error_summary: truncate(latest.error || latest.message || "benchmark cases 运行失败", 160),
      });
      throw new Error(latest.error || latest.message || "benchmark cases 运行失败");
    }

    frontendLogger.info("ui.benchmark.job_completed", {
      job_id: job.id,
      stage: latest.stage,
      status: latest.status,
      progress: Number(latest.progress || 100),
      total: latest.total,
      accuracy: latest.result?.accuracy,
      duration_ms: Math.round(performance.now() - startedAt),
    });
    state.benchmarkUploadProgress = 100;
    state.benchmarkUploadResult = latest.result;
    state.errors = null;
    state.triage = null;
    state.errorsError = "";
    state.promotions = null;
    state.promotionsError = "";
    await loadBenchmark();
    state.benchmarkUploadProgress = 100;
  } catch (error) {
    state.benchmarkUploadError = error.message;
    frontendLogger.error("ui.benchmark.upload_error", {
      file_name: file.name,
      file_size: file.size,
      duration_ms: Math.round(performance.now() - startedAt),
      error_type: errorType(error),
      error_summary: errorSummary(error),
    });
  } finally {
    state.benchmarkUploading = false;
    render();
  }
}

async function loadErrors() {
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
  render();
}

async function loadPromotions() {
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
    frontendLogger.error("ui.promotions.load_error", {
      duration_ms: Math.round(performance.now() - startedAt),
      error_type: errorType(error),
      error_summary: errorSummary(error),
    });
  }
  render();
}

async function applyPromotions() {
  if (state.applyingPromotions) return;
  const items = state.promotions?.items || [];
  const newCount = state.promotions?.new_item_count || 0;
  if (!items.length || !newCount) return;

  const startedAt = performance.now();
  frontendLogger.info("ui.promotions.apply_confirm", {
    total_items: state.promotions?.total_items,
    new_item_count: newCount,
    already_exists_count: state.promotions?.already_exists_count,
  });
  state.promotionConfirmOpen = false;
  state.applyingPromotions = true;
  state.promotionApplyProgress = 8;
  state.promotionApplyResult = null;
  state.promotionApplyError = "";
  render();

  const timer = window.setInterval(() => {
    if (!state.applyingPromotions) {
      window.clearInterval(timer);
      return;
    }
    state.promotionApplyProgress = Math.min(88, state.promotionApplyProgress + 8);
    render();
  }, 160);

  try {
    const result = await fetchJson("/candidate-promotions/apply", { method: "POST" });
    window.clearInterval(timer);
    state.promotionApplyProgress = 100;
    state.promotionApplyResult = result;
    state.applyingPromotions = false;
    frontendLogger.info("ui.promotions.apply_ok", {
      duration_ms: Math.round(performance.now() - startedAt),
      appended_count: result?.appended_count,
      skipped_count: result?.skipped_count,
    });
    await loadPromotions();
    state.promotionApplyProgress = 100;
    state.promotionApplyResult = result;
  } catch (error) {
    window.clearInterval(timer);
    state.applyingPromotions = false;
    state.promotionApplyError = error.message;
    frontendLogger.error("ui.promotions.apply_error", {
      duration_ms: Math.round(performance.now() - startedAt),
      error_type: errorType(error),
      error_summary: errorSummary(error),
    });
  } finally {
    render();
  }
}

async function applySinglePromotion() {
  if (state.singlePromotionApplying || !state.singlePromotionItem) return;
  const startedAt = performance.now();
  frontendLogger.info("ui.promotions.apply_single_confirm", {
    abbreviation: state.singlePromotionItem.abbreviation,
    expansion_hash: hashText(state.singlePromotionItem.expansion),
    domain: state.singlePromotionItem.domain,
  });
  state.singlePromotionConfirmOpen = false;
  state.singlePromotionApplying = true;
  state.singlePromotionProgress = 10;
  state.singlePromotionError = "";
  render();

  const timer = window.setInterval(() => {
    if (!state.singlePromotionApplying) {
      window.clearInterval(timer);
      return;
    }
    state.singlePromotionProgress = Math.min(88, state.singlePromotionProgress + 10);
    render();
  }, 140);

  try {
    const result = await fetchJson("/candidate-promotions/apply-single", {
      method: "POST",
      body: JSON.stringify(state.singlePromotionItem),
    });
    window.clearInterval(timer);
    state.singlePromotionProgress = 100;
    state.singlePromotionResults = {
      ...state.singlePromotionResults,
      [state.singlePromotionKey]: result,
    };
    state.singlePromotionApplying = false;
    frontendLogger.info("ui.promotions.apply_single_ok", {
      duration_ms: Math.round(performance.now() - startedAt),
      abbreviation: state.singlePromotionItem.abbreviation,
      expansion_hash: hashText(state.singlePromotionItem.expansion),
      domain: state.singlePromotionItem.domain,
      appended_count: result?.appended_count,
      skipped_count: result?.skipped_count,
    });
  } catch (error) {
    window.clearInterval(timer);
    state.singlePromotionApplying = false;
    state.singlePromotionError = error.message;
    frontendLogger.error("ui.promotions.apply_single_error", {
      duration_ms: Math.round(performance.now() - startedAt),
      abbreviation: state.singlePromotionItem.abbreviation,
      expansion_hash: hashText(state.singlePromotionItem.expansion),
      domain: state.singlePromotionItem.domain,
      error_type: errorType(error),
      error_summary: errorSummary(error),
    });
  } finally {
    render();
  }
}

function loadRouteData(route) {
  if (route === "benchmarkOverview" && !state.benchmark) loadBenchmark();
  if (route === "benchmarkErrors" && !state.errors) loadErrors();
  if (route === "benchmarkPromotions" && !state.promotions) loadPromotions();
}

function renderShell(content) {
  const meta = routes[state.route];
  app.innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <div class="brand">
          <img class="sidebar-logo" src="/frontend/assets/medical-nlp-sidebar-logo.png" alt="Medical NLP V11" />
          <div class="brand-subtitle">缩写扩写、标准化、错误复盘与候选沉淀工作台</div>
        </div>
        <nav class="nav">
          <button class="${state.route === "analyze" ? "active" : ""}" data-route="analyze">
            <span>${navIcon("analyze")}</span>
            <span>Analyze</span>
          </button>
          <div class="nav-group">
            <div class="nav-label">Benchmark</div>
            ${[
              ["benchmarkOverview", "Overview"],
              ["benchmarkErrors", "Error Analysis"],
              ["benchmarkPromotions", "Fallback Promotions"],
            ].map(([key, label]) => `
              <button class="sub ${state.route === key ? "active" : ""}" data-route="${key}">
                <span>${navIcon(key)}</span>
                <span>${label}</span>
              </button>
            `).join("")}
          </div>
        </nav>
      </aside>
      <main class="main">
        <header class="topbar">
          <div class="topbar-left">
            <div class="page-title">${meta.title}</div>
            <div class="page-kicker">${meta.kicker}</div>
          </div>
        </header>
        <section class="content">
          ${state.healthError ? `<div class="notice">API health 检查失败：${escapeHtml(state.healthError)}</div>` : ""}
          ${content}
        </section>
      </main>
      ${renderPromotionConfirmModal()}
      ${renderSinglePromotionConfirmModal()}
    </div>
  `;

  document.querySelectorAll("[data-route]").forEach((button) => {
    button.addEventListener("click", () => setRoute(button.dataset.route));
  });

}

function renderPromotionConfirmModal() {
  if (!state.promotionConfirmOpen) return "";
  const newCount = state.promotions?.new_item_count || 0;
  const total = state.promotions?.total_items || 0;
  return `
    <div class="modal-backdrop" role="presentation">
      <div class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="promotionConfirmTitle">
        <div>
          <div class="confirm-title" id="promotionConfirmTitle">确认写入 primary 缩写词典？</div>
          <div class="confirm-text">
            本次将把 ${newCount} 个新候选 append 到 <strong>backend/data/abbr_candidates.py</strong>。
            当前候选列表共 ${total} 条，已存在候选会自动跳过。
          </div>
        </div>
        <div class="confirm-actions">
          <button class="btn ghost" id="cancelPromotionApply">取消</button>
          <button class="btn primary" id="confirmPromotionApply">确认写入</button>
        </div>
      </div>
    </div>
  `;
}

function renderSinglePromotionConfirmModal() {
  if (!state.singlePromotionConfirmOpen || !state.singlePromotionItem) return "";
  const item = state.singlePromotionItem;
  return `
    <div class="modal-backdrop" role="presentation">
      <div class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="singlePromotionConfirmTitle">
        <div>
          <div class="confirm-title" id="singlePromotionConfirmTitle">写入当前 fallback 候选？</div>
          <div class="confirm-text">
            将把 <strong>${escapeHtml(item.abbreviation)}</strong> -> <strong>${escapeHtml(item.expansion)}</strong>
            append 到 <strong>backend/data/abbr_candidates.py</strong>。
            如果 primary 中已经存在相同扩写，会自动跳过。
          </div>
        </div>
        <div class="confirm-actions">
          <button class="btn ghost" id="cancelSinglePromotion">取消</button>
          <button class="btn primary" id="confirmSinglePromotion">确认写入</button>
        </div>
      </div>
    </div>
  `;
}

function navIcon(key) {
  return {
    analyze: "⌁",
    benchmarkOverview: "▥",
    benchmarkErrors: "!",
    benchmarkPromotions: "+",
  }[key] || "•";
}

function render() {
  const content = {
    analyze: renderAnalyze(),
    benchmarkOverview: renderBenchmark(),
    benchmarkErrors: renderErrors(),
    benchmarkPromotions: renderPromotions(),
  }[state.route];

  renderShell(content);
  bindRouteEvents();
}

function bindRouteEvents() {
  if (state.route === "analyze") {
    const textarea = document.getElementById("inputText");
    textarea.addEventListener("input", (event) => {
      state.text = event.target.value;
    });
    document.getElementById("runAnalyze").addEventListener("click", runAnalyze);
    const diagnosisButton = document.getElementById("runDiagnosis");
    if (diagnosisButton) diagnosisButton.addEventListener("click", runDiagnosis);
    document.getElementById("clearText").addEventListener("click", () => {
      frontendLogger.info("ui.analyze.clear_click");
      state.text = "";
      state.analyzeResult = null;
      state.diagnosis = null;
      state.diagnosisError = "";
      render();
    });
    document.querySelectorAll("[data-sample]").forEach((button) => {
      button.addEventListener("click", () => {
        state.text = samples[Number(button.dataset.sample)];
        frontendLogger.info("ui.analyze.sample_click", {
          sample_index: Number(button.dataset.sample),
          ...safeTextMeta(state.text),
        });
        render();
      });
    });
    document.querySelectorAll("[data-single-promote]").forEach((button) => {
      button.addEventListener("click", () => {
        const encoded = button.dataset.singlePromote || "";
        const payload = JSON.parse(decodeURIComponent(encoded));
        state.singlePromotionItem = payload;
        state.singlePromotionKey = promotionKey(payload);
        state.singlePromotionConfirmOpen = true;
        state.singlePromotionError = "";
        frontendLogger.info("ui.promotions.apply_single_click", {
          abbreviation: payload.abbreviation,
          expansion_hash: hashText(payload.expansion),
          domain: payload.domain,
        });
        render();
      });
    });
    const cancelSingle = document.getElementById("cancelSinglePromotion");
    if (cancelSingle) cancelSingle.addEventListener("click", () => {
      state.singlePromotionConfirmOpen = false;
      frontendLogger.info("ui.promotions.apply_single_cancel", {
        abbreviation: state.singlePromotionItem?.abbreviation,
        expansion_hash: hashText(state.singlePromotionItem?.expansion),
        domain: state.singlePromotionItem?.domain,
      });
      render();
    });
    const confirmSingle = document.getElementById("confirmSinglePromotion");
    if (confirmSingle) confirmSingle.addEventListener("click", applySinglePromotion);
  }

  if (state.route === "benchmarkOverview") {
    const refresh = document.getElementById("refreshBenchmark");
    if (refresh) refresh.addEventListener("click", () => {
      frontendLogger.info("ui.benchmark.refresh_click");
      loadBenchmark();
    });
    const uploadButton = document.getElementById("uploadBenchmarkButton");
    const uploadInput = document.getElementById("benchmarkUploadInput");
    if (uploadButton && uploadInput) {
      uploadButton.addEventListener("click", () => {
        frontendLogger.info("ui.benchmark.upload_button_click");
        uploadInput.click();
      });
      uploadInput.addEventListener("change", () => {
        const file = uploadInput.files?.[0];
        uploadBenchmarkFile(file);
        uploadInput.value = "";
      });
    }
  }

  if (state.route === "benchmarkErrors") {
    const refresh = document.getElementById("refreshErrors");
    if (refresh) refresh.addEventListener("click", () => {
      frontendLogger.info("ui.errors.refresh_click");
      loadErrors();
    });
    document.querySelectorAll("[data-error-slice]").forEach((item) => {
      item.addEventListener("click", () => {
        state.selectedErrorSlice = item.dataset.errorSlice || "all";
        frontendLogger.info("ui.errors.slice_select", {
          selected_error_slice: state.selectedErrorSlice,
        });
        render();
      });
    });
  }

  if (state.route === "benchmarkPromotions") {
    const refresh = document.getElementById("refreshPromotions");
    if (refresh) refresh.addEventListener("click", () => {
      frontendLogger.info("ui.promotions.refresh_click");
      loadPromotions();
    });
    const apply = document.getElementById("applyPromotions");
    if (apply) apply.addEventListener("click", () => {
      state.promotionConfirmOpen = true;
      frontendLogger.info("ui.promotions.apply_click", {
        total_items: state.promotions?.total_items,
        new_item_count: state.promotions?.new_item_count,
        already_exists_count: state.promotions?.already_exists_count,
      });
      render();
    });
    const cancel = document.getElementById("cancelPromotionApply");
    if (cancel) cancel.addEventListener("click", () => {
      state.promotionConfirmOpen = false;
      frontendLogger.info("ui.promotions.apply_cancel");
      render();
    });
    const confirm = document.getElementById("confirmPromotionApply");
    if (confirm) confirm.addEventListener("click", applyPromotions);
  }
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

function renderBenchmarkUploadStatusLegacy() {
  if (state.benchmarkUploading) {
    return `
      <div class="apply-status">
        <div class="apply-status-row">
          <span>正在运行上传的 benchmark cases...</span>
          <strong>${state.benchmarkUploadProgress}%</strong>
        </div>
        <div class="progress-track">
          <div class="progress-fill" style="width:${state.benchmarkUploadProgress}%"></div>
        </div>
      </div>
    `;
  }

  if (state.benchmarkUploadResult) {
    return `
      <div class="apply-status success">
        <div class="checkmark" aria-hidden="true">
          <svg viewBox="0 0 52 52">
            <circle cx="26" cy="26" r="24"></circle>
            <path d="M15 27.5 L23 35 L38 18"></path>
          </svg>
        </div>
        <div>
          <div class="apply-success-title">上传完成</div>
          <div class="apply-success-text">
            当前 benchmark：${state.benchmarkUploadResult.correct}/${state.benchmarkUploadResult.total}
            ，accuracy ${percent(state.benchmarkUploadResult.accuracy)}。
            已重新生成 Error Analysis、LLM Triage 和 Fallback Promotions。
          </div>
        </div>
      </div>
    `;
  }

  if (state.benchmarkUploadError) {
    return `<div class="notice bad-notice">上传失败：${escapeHtml(state.benchmarkUploadError)}</div>`;
  }

  return `<div class="notice">上传 benchmark cases JSON 后，后端会逐条运行主链路，并把本轮结果写入当前 benchmark_results.json。</div>`;
}

function renderBenchmarkUploadStatus() {
  if (state.benchmarkUploading) {
    const job = state.benchmarkUploadJob || {};
    const progress = Math.max(0, Math.min(100, Number(job.progress ?? state.benchmarkUploadProgress ?? 0)));
    const caseProgress = job.total
      ? `<span class="upload-step-meta">${Number(job.current || 0)} / ${Number(job.total || 0)} cases</span>`
      : "";
    const stageLabel = {
      reading_file: "读取文件",
      queued: "排队中",
      preparing: "准备运行",
      running_benchmark: "运行 benchmark",
      saving_results: "保存结果",
      error_analysis_report: "错误分析",
      error_triage: "LLM 解读",
      fallback_promotions: "候选沉淀",
      completed: "完成",
      failed: "失败",
    }[job.stage] || "运行中";

    return `
      <div class="apply-status">
        <div class="apply-status-row">
          <span>
            <strong>${escapeHtml(stageLabel)}</strong>
            <span class="upload-step-message">${escapeHtml(job.message || "正在运行上传的 benchmark cases")}</span>
            ${caseProgress}
          </span>
          <strong>${progress}%</strong>
        </div>
        <div class="progress-track">
          <div class="progress-fill" style="width:${progress}%"></div>
        </div>
      </div>
    `;
  }

  if (state.benchmarkUploadResult) {
    return `
      <div class="apply-status success">
        <div class="checkmark" aria-hidden="true">
          <svg viewBox="0 0 52 52">
            <circle cx="26" cy="26" r="24"></circle>
            <path d="M15 27.5 L23 35 L38 18"></path>
          </svg>
        </div>
        <div>
          <div class="apply-success-title">上传完成</div>
          <div class="apply-success-text">
            当前 benchmark：${state.benchmarkUploadResult.correct}/${state.benchmarkUploadResult.total}，
            accuracy ${percent(state.benchmarkUploadResult.accuracy)}。
            已重新生成 Error Analysis、LLM Triage 和 Fallback Promotions。
          </div>
        </div>
      </div>
    `;
  }

  if (state.benchmarkUploadError) {
    return `<div class="notice bad-notice">上传失败：${escapeHtml(state.benchmarkUploadError)}</div>`;
  }

  return `<div class="notice">上传 benchmark cases JSON 后，后端会逐条运行主链路，并把本轮结果写入当前 benchmark_results.json。</div>`;
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
          ? buildSinglePromotionItem(item, concept)
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
            ${promotionItem ? renderSinglePromotionStatus(promotionItem) : ""}
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
        <div class="panel-title">LLM 人话解释</div>
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

function renderSinglePromotionStatus(item) {
  const key = promotionKey(item);
  const result = state.singlePromotionResults[key];
  const isApplying = state.singlePromotionApplying && state.singlePromotionKey === key;

  if (isApplying) {
    return `
      <div class="inline-apply-status">
        <div class="apply-status-row">
          <span>正在写入 primary...</span>
          <strong>${state.singlePromotionProgress}%</strong>
        </div>
        <div class="progress-track">
          <div class="progress-fill" style="width:${state.singlePromotionProgress}%"></div>
        </div>
      </div>
    `;
  }

  if (result) {
    const appended = result.appended_count || 0;
    return `
      <div class="inline-apply-status success">
        <span class="mini-check">✓</span>
        <span>${appended ? "已写入 primary" : "该候选已在 primary 中"}</span>
      </div>
    `;
  }

  if (state.singlePromotionError && state.singlePromotionKey === key) {
    return `<div class="notice bad-notice" style="margin-top:10px;">写入失败：${escapeHtml(state.singlePromotionError)}</div>`;
  }

  return `<div class="single-promotion-hint">该结果来自 fallback 且已 CODED，可沉淀到 primary 候选库。</div>`;
}

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

function renderBenchmark() {
  if (state.benchmarkError) {
    return `<div class="notice">Benchmark 读取失败：${escapeHtml(state.benchmarkError)}</div>`;
  }

  if (!state.benchmark) {
    return `<div class="empty">正在读取 benchmark_results.json...</div>`;
  }

  const data = state.benchmark;
  const categoryStats = data.category_stats || {};
  const results = data.results || [];
  const total = data.total || 0;
  const correct = data.correct || 0;
  const failed = Math.max(0, total - correct);
  const failedCases = results.filter((item) => item.correct === false);

  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="panel-title">上传并运行 Benchmark Cases</div>
          <div class="panel-subtitle">上传包含 cases 的 JSON 文件；后端会真正运行 benchmark 并重建后续分析。</div>
        </div>
        <div class="actions inline">
          <input class="file-input" id="benchmarkUploadInput" type="file" accept=".json,application/json" />
          <button class="btn primary" id="uploadBenchmarkButton" ${state.benchmarkUploading ? "disabled" : ""}>
            ${state.benchmarkUploading ? "运行中..." : "上传 cases 并运行"}
          </button>
        </div>
      </div>
      <div class="panel-body">
        ${renderBenchmarkUploadStatus()}
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="panel-title">Benchmark 整体表现</div>
          <div class="panel-subtitle">这里只展示 benchmark 判分口径：correct / total。</div>
        </div>
        <button class="btn ghost" id="refreshBenchmark">刷新</button>
      </div>
      <div class="panel-body">
        <div class="metric-grid">
          <div class="metric"><div class="metric-label">Total Cases</div><div class="metric-value">${total}</div></div>
          <div class="metric"><div class="metric-label">Correct Cases</div><div class="metric-value">${correct}</div></div>
          <div class="metric"><div class="metric-label">Failed Cases</div><div class="metric-value">${failed}</div></div>
          <div class="metric"><div class="metric-label">Accuracy</div><div class="metric-value">${percent(data.accuracy)}</div></div>
        </div>
      </div>
    </section>

    <div class="grid">
      <section class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-title">分类正确 / 失败</div>
            <div class="panel-subtitle">每类绿色为 correct，红色为 failed。</div>
          </div>
        </div>
        <div class="panel-body">
          ${renderCategoryStackedBars(categoryStats)}
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="panel-title">Benchmark 失败案例</div>
          <div class="panel-subtitle">只展示 correct=false 的案例，说明 expected 与 predicted 的差异。</div>
        </div>
      </div>
      <div class="panel-body">
        ${renderBenchmarkFailedCases(failedCases)}
      </div>
    </section>
  `;
}

function renderCategoryStackedBars(categoryStats) {
  const entries = Object.entries(categoryStats || {});
  if (!entries.length) return `<div class="empty">暂无 category_stats。</div>`;

  return `
    <div class="stacked-list">
      ${entries.map(([name, stat]) => {
        const total = stat.total || 0;
        const correct = stat.correct || 0;
        const failed = Math.max(0, total - correct);
        const correctWidth = total ? (correct / total) * 100 : 0;
        const failedWidth = total ? (failed / total) * 100 : 0;
        return `
          <div class="stacked-row">
            <div class="stacked-label" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
            <div class="stacked-track" aria-label="${escapeHtml(name)} correct ${correct}, failed ${failed}">
              <div class="stacked-correct" style="width:${correctWidth}%"></div>
              <div class="stacked-failed" style="width:${failedWidth}%"></div>
            </div>
            <div class="stacked-value">
              <span class="status ok">${correct}</span>
              <span class="status bad">${failed}</span>
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderBenchmarkFailedCases(failedCases) {
  if (!failedCases.length) return `<div class="empty">本轮 benchmark 没有失败案例。</div>`;

  return `<div class="case-list">${failedCases.map((item) => `
    <div class="case-item">
      <div class="case-title">
        <span>${escapeHtml(item.id || "unknown")} <span class="panel-subtitle">(${escapeHtml(item.category || "-")})</span></span>
        ${statusPill(false, "failed")}
      </div>
      <div class="case-text">${escapeHtml(item.text || "")}</div>
      <div class="diff-grid">
        <div>
          <div class="diff-label">Expected</div>
          <div class="diff-box">${escapeHtml(formatMappings(item.expected_mappings || []))}</div>
        </div>
        <div>
          <div class="diff-label">Predicted</div>
          <div class="diff-box">${escapeHtml(formatMappings(item.predicted_mappings || []))}</div>
        </div>
      </div>
      <div class="failure-reason">${escapeHtml(explainBenchmarkFailure(item))}</div>
    </div>
  `).join("")}</div>`;
}

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

function makeBucket(key, cases) {
  const [label, color, description] = bucketDefinition(key);
  return { key, label, color, description, cases };
}

function buildFailureBuckets(cases) {
  const allCases = cases || [];
  const byKey = new Map();
  ["benchmark_standardization", "expansion_blocked", "standardization_only", "benchmark_only", "benchmark_expansion", "other_failure"]
    .forEach((key) => byKey.set(key, []));

  allCases.forEach((item) => {
    byKey.get(classifyFailureCase(item))?.push(item);
  });

  return [
    makeBucket("benchmark_only", byKey.get("benchmark_only") || []),
    makeBucket("expansion_blocked", byKey.get("expansion_blocked") || []),
    makeBucket("standardization_only", byKey.get("standardization_only") || []),
    makeBucket("benchmark_standardization", byKey.get("benchmark_standardization") || []),
    makeBucket("benchmark_expansion", byKey.get("benchmark_expansion") || []),
    makeBucket("other_failure", byKey.get("other_failure") || []),
  ].filter((bucket) => bucket.cases.length > 0);
}

function polarPoint(angle, radius, center = 110) {
  const radians = (angle * Math.PI) / 180;
  return {
    x: center + radius * Math.cos(radians),
    y: center + radius * Math.sin(radians),
  };
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

function ringSlices(buckets, total) {
  let cursor = 0;
  return buckets.map((bucket) => {
    const start = cursor;
    const size = total ? (bucket.cases.length / total) * 100 : 0;
    cursor += size;
    return { ...bucket, start, end: cursor };
  });
}

function renderFailureTypePie(failedCases) {
  const total = (failedCases || []).length;
  if (!total) return `<div class="empty">暂无失败 case，无法生成错误类型分布。</div>`;

  const buckets = buildFailureBuckets(failedCases);
  const selected = buckets.some((bucket) => bucket.key === state.selectedErrorSlice)
    ? state.selectedErrorSlice
    : "all";
  const slices = ringSlices(buckets, total);

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
          <path
            class="pie-slice ${selected === slice.key ? "active" : ""}"
            data-error-slice="${slice.key}"
            d="${pieSlicePath(slice.start, slice.end)}"
            fill="${slice.color}">
            <title>${escapeHtml(slice.label)} ${slice.cases.length} (${percent(slice.cases.length / total)})</title>
          </path>
          <path
            class="pie-leader"
            d="M ${edge.x.toFixed(1)} ${edge.y.toFixed(1)} Q ${elbow.x.toFixed(1)} ${elbow.y.toFixed(1)} ${labelX.toFixed(1)} ${labelY.toFixed(1)}"
            stroke="${slice.color}">
          </path>
          <text
            class="pie-label"
            x="${labelX.toFixed(1)}"
            y="${labelY.toFixed(1)}"
            text-anchor="${anchor}">
            ${escapeHtml(slice.label)}: ${percent(slice.cases.length / total)}
          </text>
        `;
        }).join("")}
      </svg>
      <div class="pie-bottom-legend">
        <button class="pie-legend-item ${selected === "all" ? "active" : ""}" data-error-slice="all">
          <span class="legend-dot" style="background:#111827"></span>
          <span>全部失败</span>
        </button>
        ${slices.map((slice) => `
          <button class="pie-legend-item ${selected === slice.key ? "active" : ""}" data-error-slice="${slice.key}">
            <span class="legend-dot" style="background:${slice.color}"></span>
            <span>${escapeHtml(slice.label)}</span>
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

function selectedFailureBucket(failedCases) {
  if (state.selectedErrorSlice === "all") {
    return {
      key: "all",
      label: "全部失败",
      description: "显示本轮错误分析报告的全部内容。",
      cases: failedCases || [],
    };
  }
  return buildFailureBuckets(failedCases).find((bucket) => bucket.key === state.selectedErrorSlice) || null;
}

function extractMarkdownBetween(markdown, startHeading, endHeadingPattern) {
  const start = markdown.indexOf(startHeading);
  if (start < 0) return "";
  const rest = markdown.slice(start);
  const end = rest.search(endHeadingPattern);
  return end > 0 ? rest.slice(0, end).trim() : rest.trim();
}

function extractCaseMarkdown(markdown, caseIds) {
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

function parseTriageCards(markdown) {
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
        const text = line.replace(/^-\s*/, "").trim();
        if (text.startsWith("失败标签:")) {
          skippingLabelBlock = text.includes("[") && !text.includes("]");
          card.labels = text.replace("失败标签:", "").replace(/[[\]`]/g, "").trim();
        } else if (text.startsWith("发生了什么:")) {
          skippingLabelBlock = false;
          card.what = text.replace("发生了什么:", "").trim();
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

function renderTriageCards(markdown, emptyText) {
  const cards = parseTriageCards(markdown);
  if (!cards.length) {
    return `<div class="empty">${escapeHtml(emptyText || "当前筛选下没有可展示的人话解释。")}</div>`;
  }

  return `
    <div class="triage-card-list">
      ${cards.map((card) => `
        <article class="triage-card">
          <div class="triage-card-head">
            <div class="triage-case-id">${escapeHtml(card.title)}</div>
            ${card.labels ? `<div class="triage-labels">${escapeHtml(card.labels)}</div>` : ""}
          </div>
          ${card.what ? `
            <div class="triage-section">
              <div class="triage-section-title">情况</div>
              <p>${escapeHtml(card.what)}</p>
            </div>
          ` : ""}
          ${card.reason ? `
            <div class="triage-section">
              <div class="triage-section-title">可能原因</div>
              <p>${escapeHtml(card.reason)}</p>
            </div>
          ` : ""}
          ${card.suggestion ? `
            <div class="triage-section suggestion">
              <div class="triage-section-title">下一步建议</div>
              <p>${escapeHtml(card.suggestion)}</p>
            </div>
          ` : ""}
          ${card.extra.length ? `
            <div class="triage-extra">
              ${card.extra.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
            </div>
          ` : ""}
        </article>
      `).join("")}
    </div>
  `;
}

function renderFilteredTriage(failedCases) {
  if (!state.triage?.exists) return `<div class="empty">还没有生成 error_triage_report.md。</div>`;
  const bucket = selectedFailureBucket(failedCases);
  const markdown = state.triage.markdown || "";
  const caseIds = (bucket?.cases || []).map((item) => item.id || item.case_id).filter(Boolean);
  const body = bucket?.key === "all"
    ? extractMarkdownBetween(markdown, "## 9. 总失败样例的人话解释", /^##\s+10\./m)
    : extractCaseMarkdown(markdown, caseIds);

  return `
    <div class="filter-note">
      当前筛选：<strong>${escapeHtml(bucket?.label || "全部失败")}</strong>，共 ${bucket?.cases?.length ?? failedCases.length} 个 case。${escapeHtml(bucket?.description || "只展示 LLM 整理后的人话解释，不展示原始 JSON 诊断字段。")}
    </div>
    ${renderTriageCards(body, `当前报告没有找到这些 case 的人话解释：${caseIds.join(", ")}`)}
  `;
}

function renderErrors() {
  if (state.errorsError) {
    return `<div class="notice">错误分析读取失败：${escapeHtml(state.errorsError)}</div>`;
  }

  if (!state.errors) {
    return `<div class="empty">正在读取 error_analysis_report.json 和 error_triage_report.md...</div>`;
  }

  const summary = state.errors.overall_failure_analysis || {};
  const failedCases = summary.failure_cases || state.errors.failed_cases || state.errors.failure_cases || [];

  return `
    <section class="panel">
      <div class="panel-header">
        <div>
            <div class="panel-title">Benchmark 失败口径</div>
            <div class="panel-subtitle">基于 error_analysis_report.json；总体失败集合 = benchmark_mismatch ∪ expansion_blocked ∪ standardization_failure。</div>
        </div>
        <button class="btn ghost" id="refreshErrors">刷新</button>
      </div>
      <div class="panel-body">
        <div class="metric-grid">
          <div class="metric"><div class="metric-label">Overall Success</div><div class="metric-value">${summary.overall_success_count ?? "-"}</div></div>
          <div class="metric"><div class="metric-label">Overall Failure</div><div class="metric-value">${summary.overall_failure_count ?? "-"}</div></div>
          <div class="metric"><div class="metric-label">Success Rate</div><div class="metric-value">${percent(summary.overall_success_rate)}</div></div>
          <div class="metric"><div class="metric-label">Failure Cases</div><div class="metric-value">${failedCases.length}</div></div>
        </div>
      </div>
    </section>

    <div class="grid">
      <section class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-title">失败类型分布</div>
            <div class="panel-subtitle">普通饼图展示各错误类型占比；交集作为独立扇区展示，点击扇区或图例筛选下方解释。</div>
          </div>
        </div>
        <div class="panel-body">${renderFailureTypePie(failedCases)}</div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-header">
        <div>
            <div class="panel-title">Benchmark LLM Triage 报告</div>
          <div class="panel-subtitle">只展示 LLM 解释；点击上方错误类型后展示对应 case。</div>
        </div>
      </div>
      <div class="panel-body">
        ${renderFilteredTriage(failedCases)}
      </div>
    </section>
  `;
}

function renderPromotionApplyStatus() {
  if (state.applyingPromotions) {
    return `
      <div class="apply-status">
        <div class="apply-status-row">
          <span>正在写入 primary 缩写词典...</span>
          <strong>${state.promotionApplyProgress}%</strong>
        </div>
        <div class="progress-track">
          <div class="progress-fill" style="width:${state.promotionApplyProgress}%"></div>
        </div>
      </div>
    `;
  }

  if (state.promotionApplyResult) {
    const appended = state.promotionApplyResult.appended_count ?? 0;
    const skipped = state.promotionApplyResult.skipped_count ?? 0;
    return `
      <div class="apply-status success">
        <div class="checkmark" aria-hidden="true">
          <svg viewBox="0 0 52 52">
            <circle cx="26" cy="26" r="24"></circle>
            <path d="M15 27.5 L23 35 L38 18"></path>
          </svg>
        </div>
        <div>
          <div class="apply-success-title">写入完成</div>
          <div class="apply-success-text">新增 ${appended} 个候选，跳过 ${skipped} 个已存在或无效候选。</div>
        </div>
      </div>
    `;
  }

  if (state.promotionApplyError) {
    return `<div class="notice bad-notice">写入失败：${escapeHtml(state.promotionApplyError)}</div>`;
  }

  return `<div class="notice" style="margin-top:14px;">确认后会把未存在的新候选 append 到 backend/data/abbr_candidates.py；同一缩写可保留多个扩写。</div>`;
}

function renderPromotions() {
  if (state.promotionsError) {
    return `<div class="notice">候选沉淀读取失败：${escapeHtml(state.promotionsError)}</div>`;
  }

  if (!state.promotions) {
    return `<div class="empty">正在读取 fallback_candidate_promotions.json...</div>`;
  }

  const items = state.promotions.items || [];
  const canApply = Boolean(items.length && (state.promotions.new_item_count || 0));

  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="panel-title">Benchmark fallback 候选沉淀概览</div>
          <div class="panel-subtitle">基于 benchmark 中 fallback 成功且 CODED 的案例；人工确认后写入 primary。</div>
        </div>
        <div class="actions inline">
          <button class="btn ghost" id="refreshPromotions" ${state.applyingPromotions ? "disabled" : ""}>刷新</button>
          <button class="btn primary" id="applyPromotions" ${!canApply || state.applyingPromotions ? "disabled" : ""}>
            ${state.applyingPromotions ? "写入中..." : "确认写入 primary"}
          </button>
        </div>
      </div>
      <div class="panel-body">
        <div class="metric-grid">
          <div class="metric"><div class="metric-label">Total Items</div><div class="metric-value">${state.promotions.total_items || 0}</div></div>
          <div class="metric"><div class="metric-label">New Items</div><div class="metric-value">${state.promotions.new_item_count || 0}</div></div>
          <div class="metric"><div class="metric-label">Already Exists</div><div class="metric-value">${state.promotions.already_exists_count || 0}</div></div>
        </div>
        ${renderPromotionApplyStatus()}
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="panel-title">候选列表</div>
          <div class="panel-subtitle">同一缩写允许多个扩写，写入 primary 时应 append 到 list。</div>
        </div>
      </div>
      <div class="panel-body">
        ${items.length ? table([
          "缩写", "扩写", "Domain", "Support", "Case IDs", "状态"
        ], items.map((item) => [
          item.abbreviation,
          item.expansion,
          item.domain,
          item.support_count,
          (item.case_ids || []).join(", "),
          item.already_exists ? statusPill("warn", "exists") : statusPill("ok", "new"),
        ]), true) : `<div class="empty">没有可沉淀候选。</div>`}
      </div>
    </section>
  `;
}

function renderPipeline() {
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="panel-title">V11 主链路</div>
          <div class="panel-subtitle">这里是前端展示用流程，不改变后端执行方式。</div>
        </div>
      </div>
      <div class="panel-body">
        <div class="grid">
          ${[
            ["1", "Token 识别", "从文本里识别可能的医学缩写 token。"],
            ["2", "Primary 候选召回", "优先从本地 abbr_candidates 取确定性候选。"],
            ["3", "Fallback 候选生成", "Primary 为空时由 LLM 生成候选，并记录 evidence。"],
            ["4", "Coverage 判断", "用上下文判断候选是否覆盖当前语义，避免过度扩写。"],
            ["5", "确定性替换", "从原始 text 和最新 records 渲染 expanded_text。"],
            ["6", "StdService 检索", "按 source/domain 检索 SNOMED 或药品集合。"],
            ["7", "Verifier / Reflection", "不可信时 WITHHELD 或反思重试，最终形成 mapping_states。"],
            ["8", "Benchmark / Error Analysis", "用 case 级和 record 级数据复盘失败原因。"],
          ].map(([step, title, desc]) => `
            <div class="case-item">
              <div class="case-title"><span>${step}. ${title}</span>${statusPill("info", "V11")}</div>
              <div class="case-text">${desc}</div>
            </div>
          `).join("")}
        </div>
      </div>
    </section>
  `;
}

function renderCases(cases) {
  if (!cases || !cases.length) {
    return `<div class="empty">暂无可展示 case。</div>`;
  }

  return `<div class="case-list">${cases.map((item) => {
    const id = item.id || item.case_id || "unknown";
    const category = item.category || item.error_type || "case";
    const correct = item.correct ?? item.mapping_correct ?? item.benchmark_correct;
    return `
      <div class="case-item">
        <div class="case-title">
          <span>${escapeHtml(id)} <span class="panel-subtitle">(${escapeHtml(category)})</span></span>
          ${correct === undefined ? "" : statusPill(Boolean(correct), correct ? "correct" : "failed")}
        </div>
        <div class="case-text">${escapeHtml(item.text || item.input || item.final_expanded_text || "")}</div>
      </div>
    `;
  }).join("")}</div>`;
}

function table(headers, rows, trustedHtml = false) {
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              ${row.map((cell) => `<td>${trustedHtml ? cell : escapeHtml(cell)}</td>`).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

window.addEventListener("error", (event) => {
  frontendLogger.error("frontend.error", {
    error_type: event.error?.name || "Error",
    error_summary: truncate(event.message || event.error?.message || "", 160),
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
  });
});

window.addEventListener("unhandledrejection", (event) => {
  frontendLogger.error("frontend.unhandled_rejection", {
    error_type: errorType(event.reason),
    error_summary: errorSummary(event.reason),
  });
});

frontendLogger.info("ui.app.load", {
  user_agent: navigator.userAgent,
});

checkHealth();
render();
