# pytest 与 CI 实施说明

本文记录本轮测试体系从 P0 到当前阶段的真实实现状态。

## 1. 测试目录

```text
backend/tests/manual/        历史手动调试脚本，不进入默认 pytest
backend/tests/unit/          不依赖外部服务的确定性测试
backend/tests/api/           FastAPI API 合同测试
backend/tests/integration/  需要 Docker/Milvus 的集成测试
backend/tests/live/         需要真实模型、LLM、网络的现场测试
```

## 2. P0：保留历史测试

原来位于 `backend/tests/test_*.py` 的 11 个脚本已移动到 `backend/tests/manual/`，保留项目开发阶段的人工测试痕迹。

这些脚本覆盖候选召回、fallback、Embedding、Milvus、标准化和确定性替换等手动验证场景。

其中 `test_support_htn.py` 曾经在导入时直接创建 `ABBRService`，会在 pytest 收集阶段加载模型并连接外部服务。现在已改为 `main()` 入口，只有手动执行脚本时才运行。

## 3. P1/P2：扫描与真实结果

测试清单见：

```text
backend/tests/TEST_INVENTORY.md
```

修复前首次运行 pytest 会在 `test_support_htn.py` 收集阶段失败。

修复后默认运行结果：

```text
10 tests collected
10 passed
```

## 4. P4：核心测试在哪里

### success 统计

文件：

```text
backend/tests/unit/test_core_logic.py
```

覆盖 `CODED`、`WITHHELD`、空 records、扩写成功和标准化成功的判断。

### API 合同

文件：

```text
backend/tests/api/test_api_contract.py
```

覆盖：

- `/health`；
- `/frontend-log` 非法 payload；
- `/expand/simple` 响应结构；
- `request_id`；
- `standardized_entities`。

测试使用 `FakeService`，不会调用真实模型或 Milvus。

### Benchmark 统计

文件：

```text
backend/tests/unit/test_core_logic.py
```

覆盖 `normalize_text`、`compare_text_contains` 和 `_build_category_stats`。

### fallback promotion

文件：

```text
backend/tests/unit/test_candidate_promotions.py
```

覆盖正确 case、fallback 来源、`CODED` 状态、`chosen_concept`、重复支持次数，以及错误/`WITHHELD` 候选过滤。

## 5. P5：标记实际位置

配置文件：

```text
backend/pytest.ini
```

已注册：

```ini
unit
integration
live
```

正式的 unit/API 测试文件使用：

```python
pytestmark = pytest.mark.unit
```

因此 `unit` 已经真正使用。

## 6. integration 测试

文件：

```text
backend/tests/integration/test_milvus_collections.py
```

它会连接 `MILVUS_URI`，并检查：

```text
concepts_only_name
rxnorm_concepts
```

只有设置环境变量后才会运行：

```powershell
$env:RUN_INTEGRATION="1"
python -m pytest -m integration -q
```

没有设置时会安全跳过，不会把缺少 Docker/Milvus 误判成代码失败。

## 7. live 测试

文件：

```text
backend/tests/live/test_live_pipeline.py
```

它会真实创建 `ABBRService`，分析：

```text
The patient has SOB and CP.
```

并检查真实返回是否包含 `success`、`expansion_success`、`standardization_success` 和 `final_result`。

运行方式：

```powershell
$env:RUN_LIVE="1"
python -m pytest -m live -q
```

该测试可能消耗 LLM 费用、加载 BGE-M3 并访问 Milvus，因此不进入默认 CI。

## 8. P6：pytest 配置与开发依赖

配置：

```text
backend/pytest.ini
```

默认 `addopts = -ra -m unit`，因此普通 pytest 只运行稳定的 unit/API 测试。

开发依赖：

```text
backend/requirements-dev.txt
```

它在生产依赖基础上增加 pytest 和 httpx。

## 9. P7：GitHub Actions

CI 文件：

```text
.github/workflows/ci.yml
```

它会在 push 到 `main` 或 Pull Request 时：

1. 使用 Python 3.12；
2. 安装 `backend/requirements-dev.txt`；
3. 进入 `backend/`；
4. 执行 `python -m pytest -q`。

默认 CI 不启动 Milvus、etcd、MinIO、BGE-M3 或真实 LLM。

## 10. P8：本地验证

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest --collect-only -q
..\.venv\Scripts\python.exe -m pytest -q
```

当前结果：

```text
默认：10 passed，integration/live 不参与默认运行
显式 integration：1 skipped（未设置 RUN_INTEGRATION）
显式 live：1 skipped（未设置 RUN_LIVE）
```

## 11. 当前边界

已经完成：

- 稳定的 unit 测试底座；
- API 合同测试；
- Benchmark 与 promotion 纯逻辑测试；
- Milvus integration 测试入口；
- 真实 LLM/模型 live 测试入口；
- GitHub Actions 默认 CI。

默认 CI 仍然不覆盖完整 Benchmark 端到端运行，因为那会依赖真实 LLM、BGE-M3 和 Milvus。真实链路已经可以通过 `integration` 和 `live` 标记显式验证。
