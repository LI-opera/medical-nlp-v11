# V11 Docker P7/P8 实施与验证步骤

## 1. 这两步是否建议手动完成

建议手动完成。

P1-P6 主要验证 Docker 文件、容器编排、目录挂载和 Milvus 建库脚本；P7-P8 则验证真正的使用链路：

```text
浏览器
  -> Docker 中的 API
  -> ABBRService
  -> LLM / Embedding
  -> Milvus SNOMED/RxNorm collection
  -> 前端结果展示
  -> 日志、benchmark 和错误分析产物
```

这部分如果只用 Python 命令测试，可能发现不了前端 API 地址、容器网络、挂载路径或进度轮询问题。

## 2. 开始前检查

在项目根目录执行：

```powershell
docker compose ps
```

预期至少能看到：

```text
medical-nlp-api
medical-nlp-milvus
medical-nlp-etcd
medical-nlp-minio
```

如果服务没有运行：

```powershell
docker compose up -d
```

检查 API：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
```

检查前端入口：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/app -UseBasicParsing
```

浏览器打开：

```text
http://127.0.0.1:8000/app
```

页面右上角 API 地址应填写：

```text
http://127.0.0.1:8000
```

如果 API 映射到了其他宿主机端口，以 `docker-compose.yml` 的 ports 配置为准。

## 3. P7 Analyze 测试

### 3.1 输入测试文本

进入左侧：

```text
Analyze
```

在输入框输入：

```text
The patient has SOB and CP.
```

点击：

```text
分析
```

### 3.2 预期结果

扩写文本应接近：

```text
The patient has shortness of breath and chest pain.
```

当前单句诊断中应能看到两个 record：

```text
SOB -> shortness of breath
CP  -> chest pain
```

正常情况下：

```text
status = CODED
source = primary 或 fallback
standard concept 有值
concept_id / code 有值
concept domain 有值
```

如果某个实体来自 fallback，并且已经 CODED，页面可能显示：

```text
写入 primary
```

这属于候选沉淀功能，不是本次 Docker 连通性测试的必需操作。第一次验证时不要点击写入，先确认分析链路正常。

### 3.3 Docker 侧检查

查看 API 日志：

```powershell
docker compose logs --tail 100 api
```

查看挂载到宿主机的后端日志：

```powershell
Get-ChildItem backend\logs
Get-Content backend\logs\app.jsonl -Tail 20
Get-Content backend\logs\pipeline.jsonl -Tail 20
Get-Content backend\logs\dependency.jsonl -Tail 20
```

重点检查是否出现：

```text
dependency.llm.call_ok
dependency.milvus.connect_ok
dependency.collection.load_ok
dependency.vector_search.ok
pipeline.final
api.expand_simple.end
```

### 3.4 P7 通过标准

- `/app` 页面可以打开。
- Analyze 请求不返回 500。
- `expanded_text` 正确替换 SOB 和 CP。
- 两个 record 能进入标准化结果。
- 至少能看到 Milvus 连接、集合加载或向量检索成功日志。
- `backend/logs/` 宿主机目录能看到新的日志记录。

## 4. P8 Benchmark 上传 60 条 cases

### 4.1 测试文件

使用：

```text
examples/benchmarks/upload_test_benchmark_cases_60.json
```

这个文件是网页上传格式，结构为：

```json
{
  "description": "...",
  "cases": [
    {
      "id": "...",
      "category": "...",
      "text": "...",
      "expected_mappings": []
    }
  ]
}
```

### 4.2 上传操作

进入左侧：

```text
Benchmark -> Overview
```

点击页面上方：

```text
上传 Benchmark Cases
```

选择：

```text
examples/benchmarks/upload_test_benchmark_cases_60.json
```

上传后页面会进入后台任务流程。不要连续重复点击上传按钮，否则可能同时启动多个 benchmark 任务。

### 4.3 观察进度

预期进度阶段大致为：

```text
读取上传文件
  -> 运行 benchmark cases
  -> 保存 benchmark 结果
  -> 生成错误分析数据
  -> 生成 LLM 错误解读
  -> 沉淀 fallback 候选
  -> 完成
```

运行时间可能较长，因为每个 case 可能调用：

```text
LLM 扩写
coverage 判断
Milvus 向量检索
verifier
reflection
```

### 4.4 Overview 验收

上传完成后，Overview 应显示：

```text
Total Cases = 60
Correct Cases = 本轮实际结果
Failed Cases = 60 - Correct Cases
Accuracy = Correct Cases / 60
```

分类统计的类别数量和每类 case 数量应随 JSON 内容动态变化，不应仍然显示旧 benchmark 的 74 条。

### 4.5 Error Analysis 验收

进入：

```text
Benchmark -> Error Analysis
```

确认：

- 总 case 数已经变成 60。
- 失败 case 列表来自本轮 60 条数据。
- 错误分布图已经刷新。
- 点击不同错误区域后，下面的 LLM Triage 内容随之改变。
- 不应继续展示上一轮 74 条 benchmark 的 case。

### 4.6 Fallback Promotions 验收

进入：

```text
Benchmark -> Fallback Promotions
```

确认：

- 候选列表来自本轮 60 条 benchmark。
- Case IDs 不应全部来自上一轮数据。
- 如果本轮没有符合条件的 fallback + CODED 候选，显示 0 条也是正常结果。

## 5. 产物和挂载目录检查

本轮 benchmark 完成后，宿主机应能看到：

```text
backend/evaluation/archive/benchmark_results.json
backend/evaluation/archive/error_analysis_report.json
backend/evaluation/archive/fallback_candidate_promotions.json
backend/evaluation/archive/fallback_candidate_promotions.md
backend/logs/benchmark.jsonl
backend/logs/pipeline.jsonl
backend/logs/dependency.jsonl
backend/logs/app.jsonl
```

检查文件更新时间：

```powershell
Get-ChildItem backend\evaluation\archive | Sort-Object LastWriteTime -Descending
Get-ChildItem backend\logs | Sort-Object LastWriteTime -Descending
```

## 6. 常见问题

### `/app` 能打开，但 Analyze 返回 500

优先查看：

```powershell
docker compose logs --tail 200 api
Get-Content backend\logs\dependency.jsonl -Tail 50
```

重点判断是：

```text
LLM 不可用
Milvus 不可用
collection 不存在
Embedding 模型加载失败
环境变量未注入
```

### Milvus 连接失败

检查：

```powershell
docker compose ps milvus etcd minio
Test-NetConnection 127.0.0.1 -Port 19530
```

容器内部 API 应使用：

```text
MILVUS_URI=http://milvus:19530
```

不能把容器内连接地址写成 `127.0.0.1:19530`，因为那会指向 API 容器自己。

### Benchmark 长时间停留在运行中

先检查 API 容器日志，不要立即重复上传：

```powershell
docker compose logs --tail 200 api
```

如果正在等待 LLM 或 Milvus，这是慢而不是页面卡死。

### Error Analysis 仍显示上一轮数据

检查 archive 文件更新时间：

```powershell
Get-ChildItem backend\evaluation\archive | Sort-Object LastWriteTime -Descending
```

如果结果文件已经更新但页面没有变化，刷新浏览器并重新进入对应子页面。

## 7. P7/P8 完成记录模板

完成后可以记录：

```text
P7 Analyze:
- 输入：The patient has SOB and CP.
- expanded_text：
- SOB status：
- CP status：
- SNOMED/RxNorm 检索：
- 日志是否写入：是/否

P8 Benchmark:
- 文件：upload_test_benchmark_cases_60.json
- Total Cases：
- Correct Cases：
- Accuracy：
- Error Analysis 是否刷新：是/否
- Fallback Promotions 是否刷新：是/否
- archive 产物是否更新：是/否
```
