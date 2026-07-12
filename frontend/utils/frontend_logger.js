(function () {
  function nowIso() {
    return new Date().toISOString();
  }

  function randomId(prefix) {
    const time = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
    const random = Math.random().toString(16).slice(2, 8);
    return `${prefix}_${time}_${random}`;
  }

  function hashText(value) {
    const text = String(value ?? "");
    let hash = 0;
    for (let index = 0; index < text.length; index += 1) {
      hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0;
    }
    return `h_${Math.abs(hash).toString(16)}`;
  }

  function truncate(value, maxChars = 120) {
    const text = String(value ?? "");
    return text.length > maxChars ? `${text.slice(0, maxChars)}...` : text;
  }

  function errorType(error) {
    return error?.name || "Error";
  }

  function errorSummary(error) {
    return truncate(error?.message || String(error || ""), 160);
  }

  function safeResponseSize(data) {
    try {
      return JSON.stringify(data ?? {}).length;
    } catch {
      return null;
    }
  }

  function safeTextMeta(text) {
    const value = String(text ?? "");
    const meta = {
      text_len: value.length,
      text_hash: hashText(value),
    };
    if (localStorage.getItem("medicalNlpFrontendLogPreview") === "1") {
      meta.text_preview = truncate(value, 80);
    }
    return meta;
  }

  const frontendLogger = {
    sessionId: localStorage.getItem("medicalNlpFrontendSessionId") || randomId("fe"),
    buffer: [],
    maxItems: 300,
    enabled: localStorage.getItem("medicalNlpFrontendLogDisabled") !== "1",
    flushing: false,
    contextProvider: () => ({}),

    /*
     * INFO console debug mode:
     *   localStorage.setItem("medicalNlpFrontendLogConsole", "1")
     *   Then refresh the page.
     *
     * Disable INFO console output:
     *   localStorage.removeItem("medicalNlpFrontendLogConsole")
     *   Then refresh the page.
     *
     * INFO/WARNING always enter frontendLogger.buffer.
     * ERROR enters buffer and is printed with console.error by default.
     */
    log(level, event, fields = {}) {
      if (!this.enabled) return;
      try {
        const context = this.contextProvider() || {};
        const entry = {
          ts: nowIso(),
          level,
          event,
          component: "frontend",
          route: context.route,
          api_base: context.apiBase,
          session_id: this.sessionId,
          ...fields,
        };
        this.buffer.push(entry);
        if (this.buffer.length > this.maxItems) {
          this.buffer.splice(0, this.buffer.length - this.maxItems);
        }
        if (level === "ERROR" && window.console?.error) {
          window.console.error("[frontend-log]", entry);
        } else if (localStorage.getItem("medicalNlpFrontendLogConsole") === "1" && window.console?.info) {
          window.console.info("[frontend-log]", entry);
        }
      } catch {
        // Logging must never affect the user-facing workflow.
      }
    },
    setContextProvider(provider) {
      if (typeof provider === "function") {
        this.contextProvider = provider;
      }
    },
    info(event, fields = {}) {
      this.log("INFO", event, fields);
    },
    warn(event, fields = {}) {
      this.log("WARNING", event, fields);
    },
    error(event, fields = {}) {
      this.log("ERROR", event, fields);
    },
    flush() {
      return [...this.buffer];
    },
    async flushToServer(limit = 100) {
      // 日志先进入前端缓冲区，普通 INFO 不直接打扰页面；只有显式 flush 时，
      // 才将经过清理的批次发送给后端。
      if (this.flushing) {
        return { ok: false, skipped: true, reason: "already_flushing" };
      }
      const context = this.contextProvider() || {};
      const apiBase = String(context.apiBase || "").replace(/\/$/, "");
      if (!apiBase) {
        return { ok: false, skipped: true, reason: "missing_api_base" };
      }
      const logs = this.buffer.slice(0, limit);
      if (!logs.length) {
        return { ok: true, accepted: 0, dropped: 0 };
      }

      this.flushing = true;
      try {
        const response = await fetch(`${apiBase}/frontend-log`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ logs }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.ok === false) {
          return {
            ok: false,
            status: response.status,
            status_text: response.statusText,
            ...result,
          };
        }
        this.buffer.splice(0, logs.length);
        return result;
      } catch (error) {
        return {
          ok: false,
          error_type: errorType(error),
          error_summary: errorSummary(error),
        };
      } finally {
        this.flushing = false;
      }
    },
    print(count = 30) {
      const recent = this.buffer.slice(-count);
      if (window.console?.table) {
        window.console.table(recent);
      }
      return recent;
    },
    clear() {
      this.buffer = [];
    },
  };

  localStorage.setItem("medicalNlpFrontendSessionId", frontendLogger.sessionId);
  window.frontendLogger = frontendLogger;
  window.frontendLogUtils = {
    randomId,
    hashText,
    truncate,
    errorType,
    errorSummary,
    safeResponseSize,
    safeTextMeta,
  };
})();
