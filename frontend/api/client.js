let config = null;

export function configureApiClient(nextConfig) {
  config = nextConfig;
}

export function apiUrl(path) {
  const base = String(config?.getApiBase?.() || "http://127.0.0.1:8000").replace(/\/$/, "");
  return `${base}${path}`;
}

export async function fetchJson(path, options = {}) {
  if (!config) throw new Error("API client has not been configured.");
  const startedAt = performance.now();
  const frontendRequestId = config.randomId("fe_req");
  const method = options.method || "GET";
  config.logger.info("api.request_start", {
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
      config.logger.error("api.request_error", {
        path,
        method,
        status: response.status,
        status_text: response.statusText,
        duration_ms: Math.round(performance.now() - startedAt),
        frontend_request_id: frontendRequestId,
        error_type: config.errorType(error),
        error_summary: `${response.status} ${response.statusText}`,
      });
      throw error;
    }

    const data = await response.json();
    config.logger.info("api.request_ok", {
      path,
      method,
      status: response.status,
      status_text: response.statusText,
      duration_ms: Math.round(performance.now() - startedAt),
      frontend_request_id: frontendRequestId,
      backend_request_id: data?.request_id || null,
      response_size: config.safeResponseSize(data),
    });
    return data;
  } catch (error) {
    if (!(error instanceof Error && /^\d{3}\s/.test(error.message))) {
      config.logger.error("api.request_error", {
        path,
        method,
        duration_ms: Math.round(performance.now() - startedAt),
        frontend_request_id: frontendRequestId,
        error_type: config.errorType(error),
        error_summary: config.errorSummary(error),
      });
    }
    throw error;
  }
}
