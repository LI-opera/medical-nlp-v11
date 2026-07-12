# V11 Docker P1/P2 实施方案

本文只描述 Docker 部署路线中的前两步：

```text
P1. 修 Dockerfile，让容器包含 frontend。
P2. 改 docker-compose.yml，加入 milvus / etcd / minio。
```

注意：

```text
本文是实施方案，不直接修改项目代码。
确认无误后，再按本文交给 Codex 执行。
```

---

## 1. 本次目标

当前 Docker 状态：

```text
Dockerfile 只复制 backend。
docker-compose.yml 只启动 api。
Milvus 依赖宿主机 host.docker.internal:19530。
```

这会导致两个问题：

```text
1. 容器里没有 frontend，/app 页面可能找不到 frontend/index.html。
2. docker compose 没有真正管理 Milvus，标准化检索依赖外部手动启动的 Milvus。
```

P1/P2 的目标是：

```text
1. API 容器内同时包含 backend 和 frontend。
2. docker compose 能同时启动 api、milvus、etcd、minio。
3. api 容器通过 Docker 内部服务名连接 Milvus：
   http://milvus:19530
```

---

## 2. 本次不做什么

这次只做 P1/P2，不做后续内容：

```text
不做 P3 volumes 完整挂载。
不跑 docker compose up。
不建 SNOMED collection。
不建 RxNorm collection。
不跑 Analyze 测试。
不跑 Benchmark 上传测试。
不整理 .env.example。
不做 milvus-init 自动建库服务。
```

原因：

```text
P1/P2 先解决“镜像内容完整”和“compose 服务完整”。
等这两项确认后，再进入 volumes、启动验证和建库步骤。
```

---

## 3. P1：修改 Dockerfile

### 3.1 当前问题

当前 Dockerfile 只有：

```dockerfile
COPY backend ./backend
```

但前端页面在：

```text
frontend/
```

后端 `/app` 路由会找：

```text
BACKEND_DIR.parent / "frontend"
```

容器内当前只有：

```text
/app/backend
```

缺少：

```text
/app/frontend
```

因此 `/app` 页面可能返回：

```text
Frontend not found
```

### 3.2 修改方案

在 Dockerfile 中增加：

```dockerfile
COPY frontend ./frontend
```

建议修改后的 Dockerfile：

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

### 3.3 P1 验收标准

只做静态检查即可：

```text
Dockerfile 中存在 COPY frontend ./frontend。
Dockerfile 仍然从 /app/backend 启动 uvicorn。
CMD 仍然是 api.main:app。
```

后续 P4 再通过浏览器验证：

```text
http://127.0.0.1:8000/app
```

---

## 4. P2：修改 docker-compose.yml

### 4.1 当前问题

当前 compose 只有 api：

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

问题是：

```text
1. 没有启动 Milvus。
2. API 依赖宿主机已经启动 Milvus。
3. 项目部署不可复现。
```

### 4.2 修改方案

新增三个服务：

```text
etcd
minio
milvus
```

api 改为连接 Docker 网络中的 Milvus：

```text
MILVUS_URI=http://milvus:19530
```

建议修改后的 docker-compose.yml：

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
    restart: unless-stopped

  minio:
    image: minio/minio:RELEASE.2024-12-18T13-15-44Z
    container_name: medical-nlp-minio
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    command: minio server /minio_data
    restart: unless-stopped

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
    depends_on:
      - etcd
      - minio
    restart: unless-stopped

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
    depends_on:
      - milvus
    restart: unless-stopped
```

### 4.3 为什么这次先不加 volumes

P3 才会正式加：

```text
logs volume
data volume
evaluation volume
huggingface cache volume
milvus_data volume
minio_data volume
etcd_data volume
```

这次 P2 先只验证服务结构：

```text
api + milvus + etcd + minio
```

避免一次改太多，问题不好定位。

### 4.4 P2 验收标准

只做 compose 配置静态检查：

```text
docker-compose.yml 中存在 etcd 服务。
docker-compose.yml 中存在 minio 服务。
docker-compose.yml 中存在 milvus 服务。
api.environment.MILVUS_URI 改为 http://milvus:19530。
api.depends_on 包含 milvus。
milvus.depends_on 包含 etcd 和 minio。
```

本阶段不要求：

```text
docker compose up 成功。
Milvus collection 已存在。
Analyze 可完成标准化。
```

这些留到 P4-P7。

---

## 5. P1/P2 修改后可能出现的问题

### 5.1 Docker 镜像构建变慢

原因：

```text
frontend 被复制进镜像。
```

影响很小，因为当前 frontend 是静态 HTML/CSS/JS，没有 node_modules。

### 5.2 Milvus 启动慢

Milvus 依赖 etcd 和 minio，首次启动可能需要一些时间。

P2 只写 compose，不启动，因此本阶段不处理启动慢问题。

### 5.3 depends_on 不等于 ready

`depends_on` 只能保证启动顺序，不保证 Milvus 已经 ready。

也就是说后续 P4/P5 可能需要：

```text
等待 Milvus 完全启动后再运行建库脚本。
```

如果后续发现 API 启动太早，可以在 P4/P5 阶段增加：

```text
healthcheck
wait-for-milvus
重试连接逻辑
```

P1/P2 暂不处理。

### 5.4 backend/.env 中的 MILVUS_URI 可能与 compose environment 冲突

当前 compose 同时使用：

```yaml
env_file:
  - backend/.env
environment:
  MILVUS_URI: http://milvus:19530
```

Docker Compose 中 `environment` 会覆盖 `env_file` 中同名变量。

因此即使 `backend/.env` 里是：

```text
MILVUS_URI=http://localhost:19530
```

容器内最终也会使用：

```text
MILVUS_URI=http://milvus:19530
```

这符合预期。

---

## 6. 执行时建议给 Codex 的任务范围

可以这样交给 Codex：

```text
请只做 Docker P1/P2：

1. 修改 Dockerfile，确保镜像中包含 frontend 目录。
2. 修改 docker-compose.yml，新增 etcd、minio、milvus 服务。
3. 将 api 的 MILVUS_URI 改为 http://milvus:19530。
4. 不要启动 docker compose。
5. 不要运行建库脚本。
6. 不要修改业务代码。
7. 修改后做静态检查，并更新交付版整理的改动.md。
```

---

## 7. P1/P2 完成后的下一步

P1/P2 完成后，不要立刻跑完整部署。

下一步应进入 P3：

```text
P3. 加 volumes：logs / data / evaluation / huggingface cache / milvus data。
```

原因：

```text
没有 volumes 时，Milvus 数据、日志、模型缓存都不够稳定。
```

P3 完成后，再进入：

```text
P4. docker compose up，确认 /app 能打开。
```

