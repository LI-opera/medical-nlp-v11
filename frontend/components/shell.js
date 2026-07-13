import { escapeHtml, promotionKey } from "../utils/format.js";
import { navIcon } from "../router.js";

// 应用外壳只负责导航、页面容器和事件绑定，不负责具体页面业务。
export function createShell({
  app,
  state,
  routes,
  samples,
  setRoute,
  render,
  renderers,
  actions,
  frontendLogger,
  safeTextMeta,
  hashText,
  renderPromotionConfirmModal,
  renderSinglePromotionConfirmModal,
}) {
  function renderShell(content) {
    const meta = routes[state.route];
    app.innerHTML = `
      <div class="shell">
        <aside class="sidebar">
          <div class="brand"><img class="sidebar-logo" src="/frontend/assets/medical-nlp-sidebar-logo.png" alt="Medical NLP V11" /><div class="brand-subtitle">缩写扩写、标准化、错误复盘与候选沉淀工作台</div></div>
          <nav class="nav">
            <button class="${state.route === "analyze" ? "active" : ""}" data-route="analyze"><span>${navIcon("analyze")}</span><span>Analyze</span></button>
            <div class="nav-group"><div class="nav-label">Benchmark</div>
              ${[["benchmarkOverview", "Overview"], ["benchmarkErrors", "Error Analysis"], ["benchmarkPromotions", "Fallback Promotions"]].map(([key, label]) => `<button class="sub ${state.route === key ? "active" : ""}" data-route="${key}"><span>${navIcon(key)}</span><span>${label}</span></button>`).join("")}
            </div>
          </nav>
        </aside>
        <main class="main"><header class="topbar"><div class="topbar-left"><div class="page-title">${meta.title}</div><div class="page-kicker">${meta.kicker}</div></div></header>
          <section class="content">${state.healthError ? `<div class="notice">API health 检查失败：${escapeHtml(state.healthError)}</div>` : ""}${content}</section>
        </main>
        ${renderPromotionConfirmModal(state)}
        ${renderSinglePromotionConfirmModal(state)}
      </div>
    `;
    document.querySelectorAll("[data-route]").forEach((button) => button.addEventListener("click", () => setRoute(button.dataset.route)));
  }

  function bindRouteEvents() {
    if (state.route === "analyze") {
      const textarea = document.getElementById("inputText");
      textarea.addEventListener("input", (event) => { state.text = event.target.value; });
      document.getElementById("runAnalyze").addEventListener("click", actions.runAnalyze);
      const diagnosisButton = document.getElementById("runDiagnosis");
      if (diagnosisButton) diagnosisButton.addEventListener("click", actions.runDiagnosis);
      document.getElementById("clearText").addEventListener("click", () => {
        frontendLogger.info("ui.analyze.clear_click");
        state.text = "";
        state.analyzeResult = null;
        state.diagnosis = null;
        state.diagnosisError = "";
        render();
      });
      document.querySelectorAll("[data-sample]").forEach((button) => button.addEventListener("click", () => {
        state.text = samples[Number(button.dataset.sample)];
        frontendLogger.info("ui.analyze.sample_click", { sample_index: Number(button.dataset.sample), ...safeTextMeta(state.text) });
        render();
      }));
      document.querySelectorAll("[data-single-promote]").forEach((button) => button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (state.singlePromotionConfirmOpen || state.singlePromotionApplying) return;
        const payload = JSON.parse(decodeURIComponent(button.dataset.singlePromote || ""));
        state.singlePromotionItem = payload;
        state.singlePromotionKey = promotionKey(payload);
        state.singlePromotionConfirmOpen = true;
        state.singlePromotionError = "";
        frontendLogger.info("ui.promotions.apply_single_click", { abbreviation: payload.abbreviation, expansion_hash: hashText(payload.expansion), domain: payload.domain });
        render();
      }));
      const cancelSingle = document.getElementById("cancelSinglePromotion");
      if (cancelSingle) cancelSingle.addEventListener("click", (event) => { event.preventDefault(); event.stopPropagation(); state.singlePromotionConfirmOpen = false; frontendLogger.info("ui.promotions.apply_single_cancel", { abbreviation: state.singlePromotionItem?.abbreviation, expansion_hash: hashText(state.singlePromotionItem?.expansion), domain: state.singlePromotionItem?.domain }); render(); });
      const confirmSingle = document.getElementById("confirmSinglePromotion");
      if (confirmSingle) confirmSingle.addEventListener("click", (event) => { event.preventDefault(); event.stopPropagation(); actions.applySinglePromotion(event); });
    }

    if (state.route === "benchmarkOverview") {
      const refresh = document.getElementById("refreshBenchmark");
      if (refresh) refresh.addEventListener("click", () => { frontendLogger.info("ui.benchmark.refresh_click"); actions.loadBenchmark(); });
      const uploadButton = document.getElementById("uploadBenchmarkButton");
      const uploadInput = document.getElementById("benchmarkUploadInput");
      if (uploadButton && uploadInput) {
        uploadButton.addEventListener("click", () => { frontendLogger.info("ui.benchmark.upload_button_click"); uploadInput.click(); });
        uploadInput.addEventListener("change", () => { actions.uploadBenchmarkFile(uploadInput.files?.[0]); uploadInput.value = ""; });
      }
    }

    if (state.route === "benchmarkErrors") {
      const refresh = document.getElementById("refreshErrors");
      if (refresh) refresh.addEventListener("click", () => { frontendLogger.info("ui.errors.refresh_click"); actions.loadErrors(); });
      document.querySelectorAll("[data-error-slice]").forEach((item) => item.addEventListener("click", () => {
        state.selectedErrorSlice = item.dataset.errorSlice || "all";
        frontendLogger.info("ui.errors.slice_select", { selected_error_slice: state.selectedErrorSlice });
        render();
      }));
    }

    if (state.route === "benchmarkPromotions") {
      const refresh = document.getElementById("refreshPromotions");
      if (refresh) refresh.addEventListener("click", () => { frontendLogger.info("ui.promotions.refresh_click"); actions.loadPromotions(); });
      const apply = document.getElementById("applyPromotions");
      if (apply) apply.addEventListener("click", () => { state.promotionConfirmOpen = true; frontendLogger.info("ui.promotions.apply_click", { total_items: state.promotions?.total_items, new_item_count: state.promotions?.new_item_count, already_exists_count: state.promotions?.already_exists_count }); render(); });
      const cancel = document.getElementById("cancelPromotionApply");
      if (cancel) cancel.addEventListener("click", () => { state.promotionConfirmOpen = false; frontendLogger.info("ui.promotions.apply_cancel"); render(); });
      const confirm = document.getElementById("confirmPromotionApply");
      if (confirm) confirm.addEventListener("click", actions.applyPromotions);
    }
  }

  function render() {
    const content = renderers[state.route]();
    renderShell(content);
    bindRouteEvents();
  }

  return { render };
}
