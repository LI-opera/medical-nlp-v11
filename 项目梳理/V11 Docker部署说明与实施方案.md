# V11 Docker 部署说明与实施方案

本文用于解释 medical-nlp V11 当前 Docker 状态、部署时前端/后端/log/Milvus 的关系，以及下一步应该如何把项目整理成可稳定运行的 Docker Compose 部署。

当前结论先放前面：

```text
1. 现在的 Docker 配置还不是完整部署，只是一个 API 容器雏形。
2. 当前 Dockerfile 没有复制 frontend，因此容器内 /app 页面可能找不到前端文件。
3. 当前 docker-compose.yml 没有真正部署 Milvus，只是让 API 去连宿主机的 Milvus。
4. logs 应该部署，但不应该写死在镜像里，应该挂载成 volume。
5. 下一版 Docker 应该用 docker-compose 管理 api + milvus + volumes。
6. Milvus 两个集合 concepts_only_name / rxnorm_concepts 需要明确初始化流程。
```

---

## 1. 当前项目 Docker 文件是什么状态

当前根目录有两个 Docker 相关文件：

```text
Dockerfile
docker-compose.yml
```

当前 Dockerfile 核心内容：

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

它做了这些事：

```text
1. 使用 python:3.10-slim 作为基础镜像。
2. 安装 backend/requirements.txt。
3. 只复制 backend 目录。
4. 启动 FastAPI。
```

当前 docker-compose.yml 核心内容：

```yaml
services:
  api:
    build: .
    container_name: medical-nlp-api
    ports:
      - "8000:8000"
    env_file:
      - backend/.env
    environment:
      MILVUS_URI: http://host.docker.internal:19530
      MILVUS_COLLECTION_NAME: concepts_only_name
    restart: unless-stopped
```

它做了这些事：

```text
1. 构建并启动 api 容器。
2. 把宿主机 8000 映射到容器 8000。
3. 读取 backend/.env。
4. 让容器去连接宿主机上的 Milvus: host.docker.internal:19530。
```

它没有做这些事：

```text
1. 没有启动 Milvus 容器。
2. 没有启动 etcd / minio 等 Milvus 依赖。
3. 没有复制 frontend 目录到镜像。
4. 没有挂载 backend/logs。
5. 没有挂载 embedding 模型缓存。
6. 没有自动初始化 SNOMED / RxNorm 两个 Milvus collection。
```

所以当前 Docker 更准确地说是：

```text
API 容器化雏形，不是完整项目部署。
```

---

## 2. Docker 部署时前端、后端、log 要不要一起部署

要分清“运行需要”和“数据保存方式”。

### 2.1 后端必须部署

后端是核心服务：

```text
FastAPI
ABBRService
StdService
LLM 调用
Milvus 检索
Benchmark
Error Analysis
Fallback Promotions
```

Docker 中必须运行后端 API。

---

### 2.2 前端也应该部署

虽然前端是静态页面，但当前项目的前端不是独立 Vite/React 服务，而是由 FastAPI 提供：

```text
GET /app
GET /frontend/app.js
GET /frontend/styles.css
GET /frontend/utils/frontend_logger.js
```

代码位置：

```text
frontend/
backend/api/main.py
```

`backend/api/main.py` 中会寻找：

```text
BACKEND_DIR.parent / "frontend"
```

如果容器里只有：

```text
/app/backend
```

没有：

```text
/app/frontend
```

那么 `/app` 页面就会找不到前端文件。

因此下一版 Dockerfile 必须复制：

```dockerfile
COPY frontend ./frontend
```

结论：

```text
前端应该跟后端一起部署在 api 容器里。
这是当前项目最简单、最稳定的部署方式。
```

---

### 2.3 logs 也应该部署，但要用 volume

日志属于运行产物，不应该打进镜像。

当前日志路径：

```text
backend/logs/app.jsonl
backend/logs/dependency.jsonl
backend/logs/pipeline.jsonl
backend/logs/benchmark.jsonl
backend/logs/audit.jsonl
backend/logs/frontend.jsonl
backend/logs/triage/error_triage_report.md
```

Docker 部署时应该这样处理：

```text
容器内路径:
  /app/backend/logs

宿主机挂载:
  ./backend/logs:/app/backend/logs
```

这样做的好处：

```text
1. 容器删除后日志还在。
2. 本机可以直接打开 logs 查看。
3. 不污染镜像。
4. 和当前 .gitignore 规则一致。
```

结论：

```text
log 要部署，但不是复制进镜像，而是挂载 volume。
```

---

## 3. Milvus 为什么之前没有彻底部署上

当前 docker-compose.yml 中只有：

```yaml
MILVUS_URI: http://host.docker.internal:19530
```

这句话的意思不是“启动 Milvus”，而是：

```text
api 容器去连接宿主机上已经启动的 Milvus。
```

所以如果宿主机没有提前运行 Milvus：

```text
API 容器会启动，但标准化检索会失败。
```

这也是之前容易出现的问题：

```text
Docker 看起来启动了，但 Milvus 没有被 compose 管理。
```

正确的完整部署应该是：

```text
docker compose up
  同时启动:
    api
    milvus
    etcd
    minio
```

并且 API 容器应该连接 compose 网络里的 Milvus：

```text
MILVUS_URI=http://milvus:19530
```

而不是：

```text
http://host.docker.internal:19530
```

---

## 4. 当前项目的 Milvus 集合

当前标准化服务使用两个 collection：

代码位置：

```text
backend/services/std_service.py
```

配置：

```python
self.collections = {
    "snomed": os.getenv("MILVUS_COLLECTION_NAME", "concepts_only_name"),
    "rxnorm": os.getenv("MILVUS_RXNORM_COLLECTION", "rxnorm_concepts"),
}
```

也就是说当前 V11 不是一个 collection 两个字段，而是两个 collection：

```text
SNOMED:
  collection = concepts_only_name
  数据源 = backend/data/snomed_clinical.csv

RxNorm:
  collection = rxnorm_concepts
  数据源 = backend/data/rxnorm_clinical.csv
```

建库脚本：

```text
backend/tools/rebuild_milvus.py
backend/tools/rebuild_rxnorm_milvus.py
```

下一版 Docker 部署必须明确解决：

```text
1. Milvus 服务怎么启动。
2. concepts_only_name 怎么建。
3. rxnorm_concepts 怎么建。
4. API 容器启动前是否要求 collection 已存在。
```

---

## 5. Docker 部署中的模型缓存问题

项目使用 embedding 模型：

```text
BAAI/bge-m3
```

代码位置：

```text
backend/utils/embedding_config.py
backend/utils/embedding_factory.py
```

如果 Docker 容器里没有模型缓存，首次启动可能会尝试从 HuggingFace 下载模型。

这会带来几个问题：

```text
1. 国内网络不稳定。
2. 镜像启动时间很长。
3. 离线环境直接失败。
4. 每次重建容器都可能重复下载。
```

因此 Docker 部署时建议挂载模型缓存：

```yaml
volumes:
  - ./model_cache/huggingface:/root/.cache/huggingface
```

或者后续进一步优化为：

```text
构建镜像时预下载模型。
```

但第一版更建议挂载缓存，因为更灵活。

---

## 6. Docker 部署中的 API Key 问题

当前 `backend/.env` 中包含：

```text
DEEPSEEK_API_KEY
DASHSCOPE_API_KEY
MILVUS_URI
```

注意：

```text
.env 可以被 docker compose 读取。
但不要把真实 API key 提交到 GitHub。
也不要 COPY .env 到镜像里。
```

推荐做法：

```text
backend/.env
  本地真实密钥，不提交。

backend/.env.example
  示例文件，可以提交。
```

示例：

```text
DEEPSEEK_API_KEY=your_deepseek_key_here
DASHSCOPE_API_KEY=your_dashscope_key_here
MILVUS_URI=http://milvus:19530
MILVUS_COLLECTION_NAME=concepts_only_name
MILVUS_RXNORM_COLLECTION=rxnorm_concepts
LOG_TEXT_PREVIEW=0
LOG_MAX_FILE_MB=10
LOG_MAX_BACKUPS=5
```

---

## 7. 推荐的最终 Docker Compose 形态

下一版建议采用：

```text
api + milvus + etcd + minio
```

服务职责：

```text
api:
  运行 FastAPI + 前端静态页面。

milvus:
  向量数据库。

etcd:
  Milvus 元数据依赖。

minio:
  Milvus 对象存储依赖。
```

推荐网络关系：

```text
宿主机浏览器
  -> http://127.0.0.1:8000/app
  -> api 容器
  -> http://milvus:19530
  -> milvus 容器
```

推荐 volume：

```text
./backend/logs:/app/backend/logs
./backend/evaluation:/app/backend/evaluation
./backend/data:/app/backend/data
./model_cache/huggingface:/root/.cache/huggingface
milvus_data:/var/lib/milvus
minio_data:/minio_data
etcd_data:/etcd
```

说明：

```text
backend/logs:
  保存运行日志。

backend/evaluation:
  保存 benchmark_results.json、error_analysis_report.json、fallback_candidate_promotions.json。

backend/data:
  提供 snomed_clinical.csv / rxnorm_clinical.csv。

model_cache/huggingface:
  保存 bge-m3 模型缓存。

milvus_data:
  保存 Milvus collection 数据。
```

---

## 8. 推荐的 Dockerfile 改造方向

当前 Dockerfile 问题：

```text
只复制 backend，没有复制 frontend。
```

下一版应该改成：

```dockerfile
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

这样容器内会同时有：

```text
/app/backend
/app/frontend
```

FastAPI 的 `/app` 页面才能正常找到前端。

---

## 9. 推荐的 docker-compose.yml 改造方向

下面是下一版设计草案，不是当前已执行代码：

```yaml
services:
  etcd:
    image: quay.io/coreos/etcd:v3.5.18
    container_name: medical-nlp-etcd
    environment:
      ETCD_AUTO_COMPACTION_MODE: revision
      ETCD_AUTO_COMPACTION_RETENTION: "1000"
      ETCD_QUOTA_BACKEND_BYTES: "4294967296"
      ETCD_SNAPSHOT_COUNT: "50000"
    command: >
      etcd
      -advertise-client-urls=http://127.0.0.1:2379
      -listen-client-urls=http://0.0.0.0:2379
      --data-dir=/etcd
    volumes:
      - etcd_data:/etcd

  minio:
    image: minio/minio:RELEASE.2024-12-18T13-15-44Z
    container_name: medical-nlp-minio
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    command: minio server /minio_data
    volumes:
      - minio_data:/minio_data

  milvus:
    image: milvusdb/milvus:v2.5.4
    container_name: medical-nlp-milvus
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    ports:
      - "19530:19530"
      - "9091:9091"
    volumes:
      - milvus_data:/var/lib/milvus
    depends_on:
      - etcd
      - minio

  api:
    build: .
    container_name: medical-nlp-api
    ports:
      - "8000:8000"
    env_file:
      - backend/.env
    environment:
      MILVUS_URI: http://milvus:19530
      MILVUS_COLLECTION_NAME: concepts_only_name
      MILVUS_RXNORM_COLLECTION: rxnorm_concepts
      LOG_TEXT_PREVIEW: "0"
      LOG_MAX_FILE_MB: "10"
      LOG_MAX_BACKUPS: "5"
    volumes:
      - ./backend/logs:/app/backend/logs
      - ./backend/evaluation:/app/backend/evaluation
      - ./backend/data:/app/backend/data
      - ./model_cache/huggingface:/root/.cache/huggingface
    depends_on:
      - milvus
    restart: unless-stopped

volumes:
  etcd_data:
  minio_data:
  milvus_data:
```

注意：

```text
具体 Milvus 镜像版本可以后续根据本机 Docker 环境调整。
上面是部署设计草案，真正落地前需要验证 Milvus 官方 compose 版本兼容性。
```

---

## 10. Milvus 初始化方案

仅仅启动 Milvus 不够，还要把两个 collection 建进去。

当前已有脚本：

```text
backend/tools/rebuild_milvus.py
backend/tools/rebuild_rxnorm_milvus.py
```

下一步有两种做法。

### 10.1 手动初始化

第一次部署时：

```powershell
docker compose up -d milvus etcd minio
docker compose run --rm api python tools/rebuild_milvus.py
docker compose run --rm api python tools/rebuild_rxnorm_milvus.py
docker compose up -d api
```

优点：

```text
清晰、可控、适合你现在学习 Docker。
```

缺点：

```text
需要记住第一次要手动跑建库脚本。
```

### 10.2 自动初始化 init 服务

在 compose 中增加：

```yaml
milvus-init:
  build: .
  command: >
    sh -c "python tools/rebuild_milvus.py &&
           python tools/rebuild_rxnorm_milvus.py"
  env_file:
    - backend/.env
  environment:
    MILVUS_URI: http://milvus:19530
  volumes:
    - ./backend/data:/app/backend/data
    - ./model_cache/huggingface:/root/.cache/huggingface
  depends_on:
    - milvus
```

优点：

```text
部署自动化程度更高。
```

缺点：

```text
第一次建库会很慢。
每次误跑可能会 drop 并重建 collection。
如果 Milvus 尚未完全 ready，需要加 wait-for-health 逻辑。
```

当前建议：

```text
第一阶段采用手动初始化。
第二阶段再考虑 milvus-init 自动化。
```

原因：

```text
你现在正在理解项目部署，手动初始化更利于掌握每一步。
```

---

## 11. 部署后的访问方式

如果使用 docker compose 暴露：

```yaml
ports:
  - "8000:8000"
```

浏览器访问：

```text
http://127.0.0.1:8000/app
```

API 根路径：

```text
http://127.0.0.1:8000/
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

健康检查：

```text
http://127.0.0.1:8000/health
```

Milvus 端口：

```text
127.0.0.1:19530
```

---

## 12. Docker 部署后的日志查看

因为日志目录挂载为：

```yaml
./backend/logs:/app/backend/logs
```

所以你在宿主机仍然可以直接看：

```text
E:\Work\B_RAG\Try\medical-nlp\backend\logs\app.jsonl
E:\Work\B_RAG\Try\medical-nlp\backend\logs\dependency.jsonl
E:\Work\B_RAG\Try\medical-nlp\backend\logs\pipeline.jsonl
E:\Work\B_RAG\Try\medical-nlp\backend\logs\benchmark.jsonl
E:\Work\B_RAG\Try\medical-nlp\backend\logs\audit.jsonl
E:\Work\B_RAG\Try\medical-nlp\backend\logs\frontend.jsonl
```

容器日志看启动和崩溃：

```powershell
docker compose logs -f api
docker compose logs -f milvus
```

业务链路排查仍然看 jsonl：

```text
app.jsonl       看 API 收到请求没有
pipeline.jsonl  看 ABBRService 结果
dependency.jsonl 看 LLM / Milvus / Embedding
benchmark.jsonl 看 benchmark job
audit.jsonl     看写 primary
frontend.jsonl  看浏览器前端落盘事件
```

---

## 13. 部署验证清单

### 13.1 容器状态

```powershell
docker compose ps
```

期待：

```text
api     running
milvus  running
etcd    running
minio   running
```

### 13.2 API 页面

打开：

```text
http://127.0.0.1:8000/app
```

期待：

```text
能看到前端页面，而不是纯 JSON。
```

### 13.3 健康检查

打开：

```text
http://127.0.0.1:8000/health
```

期待：

```text
API ok
```

### 13.4 Milvus 连接

在页面 Analyze 输入：

```text
The patient has SOB and CP.
```

期待：

```text
SOB -> shortness of breath -> CODED
CP -> chest pain -> CODED
```

同时检查：

```text
backend/logs/dependency.jsonl
```

期待出现：

```text
dependency.milvus.connect_ok
dependency.collection.load_ok
dependency.vector_search.ok
```

### 13.5 LLM 连接

对于需要 coverage / fallback / verifier 的输入，检查：

```text
backend/logs/dependency.jsonl
```

期待出现：

```text
dependency.llm.call_ok
```

如果出现：

```text
dependency.llm.call_error
```

优先检查：

```text
DEEPSEEK_API_KEY
网络连接
容器是否能访问外网
```

### 13.6 Benchmark 上传

在 Benchmark Overview 上传：

```text
backend/evaluation/upload_test_benchmark_cases_60.json
```

期待：

```text
Overview 更新
Error Analysis 更新
Fallback Promotions 更新
benchmark.jsonl 记录 job progress
```

---

## 14. 推荐实施顺序

不要一次性把所有 Docker 自动化都做完，容易乱。

推荐顺序：

```text
P1. 修 Dockerfile，让容器包含 frontend。
P2. 改 docker-compose.yml，加入 milvus / etcd / minio。
P3. 加 volumes：logs / data / evaluation / huggingface cache / milvus data。
P4. 本地 docker compose up，确认 /app 能打开。
P5. 手动运行 rebuild_milvus.py 建 SNOMED collection。
P6. 手动运行 rebuild_rxnorm_milvus.py 建 RxNorm collection。
P7. Analyze 测试 SOB and CP。
P8. Benchmark 上传 60 条 cases 测试。
P9. 整理 .env.example 和部署 README。
P10. 后续再考虑 milvus-init 自动建库服务。
```

---

## 15. 当前不建议马上做的事

### 15.1 不建议把 Milvus 数据直接打进 API 镜像

原因：

```text
镜像会非常大。
Milvus 数据本来就应该由 volume 管理。
```

### 15.2 不建议把 logs 打进镜像

原因：

```text
logs 是运行产物。
镜像应该是干净的程序环境。
```

### 15.3 不建议把真实 .env 提交到 GitHub

原因：

```text
里面有 API key。
```

### 15.4 不建议第一版就做全自动 Milvus init

原因：

```text
建库慢。
失败点多。
你现在更需要看清每一步。
```

---

## 16. 一句话理解 Docker 部署边界

```text
API 镜像负责运行前端和后端代码；Milvus 容器负责保存向量库；logs / data / evaluation / model cache 通过 volume 保留在宿主机；SNOMED 和 RxNorm 两个 collection 需要初始化后，标准化链路才算真正可用。
```

