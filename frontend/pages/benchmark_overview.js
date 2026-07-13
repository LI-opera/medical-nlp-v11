import {
  escapeHtml,
  explainBenchmarkFailure,
  formatMappings,
  percent,
  statusPill,
} from "../utils/format.js";

// Benchmark Overview 页面模块：负责本页面的数据加载、上传轮询和展示。
export function createBenchmarkOverview({
  state,
  fetchJson,
  frontendLogger,
  errorType,
  errorSummary,
  truncate,
  render,
}) {
  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
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

  return { loadBenchmark, uploadBenchmarkFile, renderBenchmark };
}
