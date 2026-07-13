// 前端全局状态的单一来源。页面模块可以读取和更新它，但不各自复制状态。
export const state = {
  route: "analyze",
  tab: "mappings",
  text: "",
  apiBase: window.location.origin && window.location.origin !== "null"
    ? window.location.origin
    : "http://127.0.0.1:8000",
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

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch || {});
  return state;
}

export function resetAnalyzeState() {
  Object.assign(state, {
    analyzeResult: null,
    analyzeError: "",
    analyzing: false,
    diagnosis: null,
    diagnosisError: "",
    diagnosing: false,
  });
}

export function resetBenchmarkState() {
  Object.assign(state, {
    benchmark: null,
    benchmarkError: "",
    benchmarkUploadProgress: 0,
    benchmarkUploadJob: null,
    benchmarkUploadResult: null,
    benchmarkUploadError: "",
    benchmarkUploading: false,
  });
}

export function resetPromotionState() {
  Object.assign(state, {
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
  });
}
