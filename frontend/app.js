import { configureApiClient, fetchJson } from "./api/client.js";
import { state } from "./state/store.js";
import { createAnalyzeActions, createAnalyzeRenderer } from "./pages/analyze.js";
import { createBenchmarkOverview } from "./pages/benchmark_overview.js?v=20260713-benchmark-decouple-2";
import { createErrorAnalysis } from "./pages/error_analysis.js";
import { createFallbackPromotions } from "./pages/fallback_promotions.js";
import { renderPromotionConfirmModal, renderSinglePromotionConfirmModal } from "./components/modal.js?v=20260713-benchmark-decouple-2";
import { createRouter } from "./router.js";
import { createShell } from "./components/shell.js?v=20260713-benchmark-decouple-2";
const samples = [
  "The patient has SOB and CP.",
  "The patient has RA with joint pain and morning stiffness.",
  "The ABG revealed respiratory acidosis with hypoxemia.",
  "The patient has XYZ.",
  "The patient has ABC and SOB.",
];

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

configureApiClient({
  getApiBase: () => state.apiBase,
  logger: frontendLogger,
  randomId,
  errorType,
  errorSummary,
  safeResponseSize,
});


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

const { runAnalyze, runDiagnosis } = createAnalyzeActions({
  state,
  fetchJson,
  frontendLogger,
  safeTextMeta,
  safeResponseSize,
  errorType,
  errorSummary,
  render: () => render(),
});

const { renderAnalyze } = createAnalyzeRenderer({
  state,
  samples,
});

const {
  loadBenchmark,
  uploadBenchmarkFile,
  renderBenchmark,
} = createBenchmarkOverview({
  state,
  fetchJson,
  frontendLogger,
  errorType,
  errorSummary,
  truncate,
  render: () => render(),
  onBenchmarkCompleted: async () => {
    state.errors = null;
    state.triage = null;
    state.errorsError = "";
    state.promotions = null;
    state.promotionsError = "";

    // 只刷新当前所在的 benchmark 子页面，Analyze 保持原页面状态不变。
    if (state.route === "benchmarkErrors") await loadErrors({ renderPage: true });
    if (state.route === "benchmarkPromotions") await loadPromotions({ renderPage: true });
  },
});

const {
  loadErrors,
  renderErrors,
} = createErrorAnalysis({
  state,
  fetchJson,
  frontendLogger,
  errorType,
  errorSummary,
  render: () => render(),
});

const {
  loadPromotions,
  applyPromotions,
  applySinglePromotion,
  renderPromotions,
} = createFallbackPromotions({
  state,
  fetchJson,
  frontendLogger,
  errorType,
  errorSummary,
  hashText,
  render: () => render(),
});

const router = createRouter({
  state,
  frontendLogger,
  render: () => shell.render(),
  loaders: { loadBenchmark, loadErrors, loadPromotions },
});

const shell = createShell({
  app,
  state,
  routes: router.routes,
  samples,
  setRoute: router.setRoute,
  render: () => render(),
  renderers: {
    analyze: renderAnalyze,
    benchmarkOverview: renderBenchmark,
    benchmarkErrors: renderErrors,
    benchmarkPromotions: renderPromotions,
  },
  actions: {
    runAnalyze,
    runDiagnosis,
    loadBenchmark,
    uploadBenchmarkFile,
    loadErrors,
    loadPromotions,
    applyPromotions,
    applySinglePromotion,
  },
  frontendLogger,
  safeTextMeta,
  hashText,
  renderPromotionConfirmModal,
  renderSinglePromotionConfirmModal,
});

function render() {
  shell.render();
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
