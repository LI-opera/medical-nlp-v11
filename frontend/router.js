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

export function createRouter({ state, frontendLogger, render, loaders }) {
  function setRoute(route) {
    if (!routes[route]) return;
    frontendLogger.info("ui.route.change", { from_route: state.route, to_route: route });
    state.route = route;
    state.tab = "mappings";
    render();
    loadRouteData(route);
  }

  function loadRouteData(route) {
    if (route === "benchmarkOverview" && !state.benchmark) loaders.loadBenchmark();
    if (route === "benchmarkErrors" && !state.errors) loaders.loadErrors();
    if (route === "benchmarkPromotions" && !state.promotions) loaders.loadPromotions();
  }

  return { routes, setRoute, loadRouteData };
}

export function navIcon(key) {
  return {
    analyze: "⌁",
    benchmarkOverview: "▥",
    benchmarkErrors: "!",
    benchmarkPromotions: "+",
  }[key] || "•";
}
