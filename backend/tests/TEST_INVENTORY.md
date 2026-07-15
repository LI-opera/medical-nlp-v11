# 测试清单

## 当前自动化测试

| 目录 | 类型 | 文件数 | 默认执行 | 依赖 |
| --- | --- | ---: | --- | --- |
| `tests/unit/` | 纯逻辑单元测试 | 3 | 是 | Python 与项目轻量依赖 |
| `tests/api/` | FastAPI API 合同测试 | 1 | 是 | FastAPI TestClient、httpx |
| `tests/integration/` | 本地服务集成测试 | 1 | 否 | Milvus；需 `RUN_INTEGRATION=1` |
| `tests/live/` | 真实链路测试 | 1 | 否 | LLM、Embedding、Milvus；需 `RUN_LIVE=1` |
| `tests/manual/` | 历史手动调试脚本 | 11 | 否 | 视脚本而定 |

## 当前默认结果

在 `backend` 目录执行：

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

当前结果：`14 passed, 2 deselected`。

`integration` 和 `live` 测试默认不进入 CI，避免测试过程隐式启动或依赖真实外部服务。

## 历史手动脚本

`tests/manual/` 保留项目开发阶段的人工验证痕迹，包括候选召回、Embedding、Milvus、标准化和确定性替换等脚本。它们不是当前默认自动化测试入口。

## 性能测试说明

`tests/unit/test_performance_report.py` 验证性能统计函数的分位数、平均值、分类延迟和阶段日志可用性。它不运行真实 Benchmark，不调用 LLM、Embedding 或 Milvus。
