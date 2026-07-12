# V11 Docker P5/P6 实施方案

本文只描述 Docker 部署路线中的第 5、6 步：

```text
P5. 手动运行 rebuild_milvus.py 建 SNOMED collection。
P6. 手动运行 rebuild_rxnorm_milvus.py 建 RxNorm collection。
```

注意：

```text
本文是实施方案，不直接执行建库。
确认无误后，再按本文交给 Codex 执行。
```

---

## 1. 当前前提

本文默认 P1-P4 已完成并验证通过：

```text
1. Docker 镜像已包含 backend 和 frontend。
2. docker-compose.yml 已包含 api / milvus / etcd / minio。
3. Milvus 已由当前项目自己的 compose 栈启动。
4. 127.0.0.1:19530 已能连接。
5. 127.0.0.1:9091/healthz 已返回 200。
6. http://127.0.0.1:8000/app 已能打开。
```

当前 compose 中 API 容器使用：

```text
MILVUS_URI=http://milvus:19530
MILVUS_COLLECTION_NAME=concepts_only_name
MILVUS_RXNORM_COLLECTION=rxnorm_concepts
```

这意味着：

```text
在 api 容器内运行建库脚本时，脚本会连接 compose 网络里的 milvus 服务。
在宿主机运行建库脚本时，脚本应连接 http://127.0.0.1:19530。
```

本方案推荐：

```text
优先在 api 容器内手动执行建库脚本。
```

原因：

```text
1. 容器内 Python 依赖与正式部署环境一致。
2. 容器内 MILVUS_URI 已是 http://milvus:19530。
3. backend/data 已通过 volume 挂载进容器。
4. huggingface cache 已通过 volume 挂载到 /root/.cache/huggingface。
5. 避免宿主机 venv 与 Docker 环境不一致。
```

---

## 2. 当前两个 collection 的职责

V11 标准化底座不是“一个 collection 两个字段”，而是两个 collection：

```text
SNOMED collection:
  concepts_only_name

RxNorm collection:
  rxnorm_concepts
```

代码位置：

```text
backend/services/std_service.py
```

配置逻辑：

```python
self.collections = {
    "snomed": os.getenv("MILVUS_COLLECTION_NAME", "concepts_only_name"),
    "rxnorm": os.getenv("MILVUS_RXNORM_COLLECTION", "rxnorm_concepts"),
}
```

含义：

```text
普通疾病、症状、检查、解剖部位等概念 -> SNOMED collection
药品类概念 -> RxNorm collection
```

因此 P5/P6 都必须完成，否则后续 Analyze 时：

```text
非药品标准化可能可用，但药品标准化失败；
或两个 collection 都不存在，整体标准化检索失败。
```

---

## 3. 建库脚本与输入数据

### 3.1 P5 SNOMED 建库

脚本：

```text
backend/tools/rebuild_milvus.py
```

输入 CSV：

```text
backend/data/snomed_clinical.csv
```

目标 collection：

```text
concepts_only_name
```

当前 CSV 已存在：

```text
backend/data/snomed_clinical.csv
```

字段：

```text
concept_id
concept_name
domain_id
concept_code
FSN
```

脚本行为：

```text
1. 读取 snomed_clinical.csv。
2. 加载 embedding 模型 bge-m3。
3. 连接 Milvus。
4. 如果 concepts_only_name 已存在，先 drop。
5. 创建新 schema。
6. 批量 embed concept_name。
7. 批量 insert。
8. flush。
9. load collection。
10. 自测 chest pain 检索。
```

重要边界：

```text
这是重建脚本，不是增量脚本。
它会删除旧的 concepts_only_name collection。
```

---

### 3.2 P6 RxNorm 建库

脚本：

```text
backend/tools/rebuild_rxnorm_milvus.py
```

输入 CSV：

```text
backend/data/rxnorm_clinical.csv
```

目标 collection：

```text
rxnorm_concepts
```

当前 CSV 已存在：

```text
backend/data/rxnorm_clinical.csv
```

字段：

```text
concept_id
concept_name
domain_id
concept_code
FSN
```

脚本行为：

```text
1. 读取 rxnorm_clinical.csv。
2. 加载 embedding 模型 bge-m3。
3. 连接 Milvus。
4. 如果 rxnorm_concepts 已存在，先 drop。
5. 创建新 schema。
6. 批量 embed concept_name。
7. 批量 insert。
8. flush。
9. load collection。
10. 自测 aspirin 检索。
```

重要边界：

```text
rebuild_rxnorm_milvus.py 只重建 rxnorm_concepts。
它不会删除 concepts_only_name。
```

---

## 4. P5/P6 执行前检查

执行建库前先确认 compose 服务状态：

```powershell
docker compose ps
```

期望看到：

```text
medical-nlp-api      Up
medical-nlp-milvus   Up  0.0.0.0:19530->19530, 0.0.0.0:9091->9091
medical-nlp-etcd     Up
medical-nlp-minio    Up
```

检查 Milvus health：

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:9091/healthz -UseBasicParsing
```

期望：

```text
StatusCode = 200
```

检查 CSV 是否存在：

```powershell
Get-ChildItem backend\data\snomed_clinical.csv, backend\data\rxnorm_clinical.csv
```

期望：

```text
snomed_clinical.csv 存在
rxnorm_clinical.csv 存在
```

---

## 5. P5 推荐执行方式：在 api 容器内建 SNOMED

推荐命令：

```powershell
docker compose exec api python tools/rebuild_milvus.py
```

为什么不写 `backend/tools/rebuild_milvus.py`：

```text
api 容器工作目录是 /app/backend。
因此容器内脚本路径是 tools/rebuild_milvus.py。
```

预期关键输出：

```text
Reading /app/backend/data/snomed_clinical.csv
Rows: ...
Loading embedding model (bge-m3)...
Vector dim: ...
Connecting Milvus: http://milvus:19530
Dropping old collection: concepts_only_name   # 如果旧 collection 存在
Embedding + inserting rows ...
Done. Inserted ... rows
=== Self-test 'chest pain' ===
```

如果首次运行时下载 embedding 模型，可能耗时较长。
由于 P3 已挂载：

```text
./model_cache/huggingface:/root/.cache/huggingface
```

模型下载后会缓存在宿主机：

```text
model_cache/huggingface
```

后续重跑会快很多。

---

## 6. P6 推荐执行方式：在 api 容器内建 RxNorm

推荐命令：

```powershell
docker compose exec api python tools/rebuild_rxnorm_milvus.py
```

预期关键输出：

```text
Reading /app/backend/data/rxnorm_clinical.csv
Rows: ...
Loading embedding model (bge-m3)...
Vector dim: ...
Connecting Milvus: http://milvus:19530
Dropping old collection: rxnorm_concepts   # 如果旧 collection 存在
Embedding + inserting rows ...
Done. Inserted ... rows into rxnorm_concepts.
=== Self-test 'aspirin' ===
```

---

## 7. P5/P6 后验收方式

### 7.1 检查 collection 是否存在

在 api 容器内执行：

```powershell
docker compose exec api python -c "from pymilvus import MilvusClient; c=MilvusClient(uri='http://milvus:19530'); print(c.list_collections())"
```

期望至少包含：

```text
concepts_only_name
rxnorm_concepts
```

### 7.2 检查 SNOMED 检索

```powershell
docker compose exec api python -c "from pymilvus import MilvusClient; c=MilvusClient(uri='http://milvus:19530'); print(c.get_collection_stats('concepts_only_name'))"
```

期望：

```text
row_count > 0
```

### 7.3 检查 RxNorm 检索

```powershell
docker compose exec api python -c "from pymilvus import MilvusClient; c=MilvusClient(uri='http://milvus:19530'); print(c.get_collection_stats('rxnorm_concepts'))"
```

期望：

```text
row_count > 0
```

### 7.4 API 业务验收留到 P7

P5/P6 只验收：

```text
collection 创建成功
collection 有数据
collection 能 load / search
```

不在 P5/P6 验收：

```text
Analyze 业务是否成功
SOB and CP 是否标准化成功
Benchmark 是否通过
```

这些属于：

```text
P7. Analyze 测试 SOB and CP。
P8. Benchmark 上传 60 条 cases 测试。
```

---

## 8. 失败处理建议

### 8.1 连接 Milvus 失败

现象：

```text
Connect failed
connection refused
Name or service not known
```

检查：

```powershell
docker compose ps
Invoke-WebRequest -Uri http://127.0.0.1:9091/healthz -UseBasicParsing
```

如果在 api 容器内运行，应该使用：

```text
http://milvus:19530
```

如果在宿主机运行，应该使用：

```text
http://127.0.0.1:19530
```

---

### 8.2 CSV 缺失

现象：

```text
FileNotFoundError: snomed_clinical.csv
FileNotFoundError: rxnorm_clinical.csv
```

检查宿主机：

```powershell
Get-ChildItem backend\data
```

检查容器内：

```powershell
docker compose exec api ls /app/backend/data
```

如果宿主机有但容器内没有，说明 compose volume 挂载有问题。

---

### 8.3 embedding 模型加载失败

可能原因：

```text
1. 容器内网络不能下载模型。
2. huggingface cache 为空。
3. 模型路径配置不正确。
```

处理思路：

```text
1. 先确认 backend/utils/embedding_config.py 的模型配置。
2. 如果需要联网下载，允许 Docker 环境访问模型源。
3. 如果本机已有模型缓存，可以后续把缓存目录规范化挂载。
```

---

### 8.4 脚本运行时间很长

原因：

```text
1. SNOMED / RxNorm CSV 行数较多。
2. bge-m3 embedding 批量计算耗时。
3. 首次模型下载耗时。
4. Milvus insert / index / load 耗时。
```

处理：

```text
保持终端打开，不要中途关闭。
观察插入进度。
首次运行慢是正常现象。
```

---

## 9. 可选宿主机执行方式

如果不想进容器，也可以在宿主机 venv 中执行：

```powershell
$env:MILVUS_URI="http://127.0.0.1:19530"
.\.venv\Scripts\python.exe backend\tools\rebuild_milvus.py
.\.venv\Scripts\python.exe backend\tools\rebuild_rxnorm_milvus.py
```

但宿主机执行有两个前提：

```text
1. 宿主机 venv 依赖必须完整。
2. 宿主机 embedding cache / 模型下载环境必须可用。
```

因此 Docker 部署验收阶段仍推荐优先使用：

```text
docker compose exec api python tools/rebuild_milvus.py
docker compose exec api python tools/rebuild_rxnorm_milvus.py
```

---

## 10. P5/P6 完成标准

P5 完成标准：

```text
1. concepts_only_name collection 存在。
2. concepts_only_name row_count > 0。
3. rebuild_milvus.py 自测 chest pain 有返回结果。
```

P6 完成标准：

```text
1. rxnorm_concepts collection 存在。
2. rxnorm_concepts row_count > 0。
3. rebuild_rxnorm_milvus.py 自测 aspirin 有返回结果。
```

P5/P6 完成后，才能进入：

```text
P7. Analyze 测试 SOB and CP。
P8. Benchmark 上传 60 条 cases 测试。
```
