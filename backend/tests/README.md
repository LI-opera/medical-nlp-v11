# Backend 测试目录

## 目录约定

- `unit/`：不依赖 LLM、BGE-M3、Milvus 或外部网络的确定性单元测试。
- `api/`：使用 FastAPI TestClient 和假的服务对象验证 API 返回结构与错误合同。
- `manual/`：项目开发过程中保留的人工调试脚本和历史测试痕迹，不由 CI 自动执行。
- `integration/`：需要 Docker/Milvus 等本地服务的集成测试，需显式设置 `RUN_INTEGRATION=1`。
- `live/`：需要真实模型、LLM、网络或完整运行环境的现场测试，需显式设置 `RUN_LIVE=1`。

## 运行方式

在 `backend/` 目录执行：

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

默认 pytest 只运行 `unit` 标记的稳定测试。需要运行手动脚本时，直接按脚本用途单独执行，例如：

```powershell
..\.venv\Scripts\python.exe tests\manual\test_support_htn.py
```

真实服务测试命令：

```powershell
$env:RUN_INTEGRATION="1"
..\.venv\Scripts\python.exe -m pytest -m integration -q

$env:RUN_LIVE="1"
..\.venv\Scripts\python.exe -m pytest -m live -q
```

真实服务测试不进入默认 CI。
