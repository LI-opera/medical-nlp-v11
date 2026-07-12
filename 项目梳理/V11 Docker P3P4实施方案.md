# V11 Docker P3/P4 实施方案

本文只描述 Docker 部署路线中的第 3、4 步：

```text
P3. 加 volumes：logs / data / evaluation / huggingface cache / milvus data。
P4. 本地 docker compose up，确认 /app 能打开。
```

注意：

```text
本文是实施方案，不直接修改项目代码。
确认无误后，再按本文交给 Codex 执行。
```

---

## 1. 当前前提

本文默认 P1/P2 已完成：

```text
Dockerfile 已包含:
  COPY frontend ./frontend

docker-compose.yml 已包含:
  api
  milvus
  etcd
  minio

api 容器内 Milvus 地址:
  MILVUS_URI=http://milvus:19530
```

P3/P4 的目标不是建库，也不是跑完整业务链路。

P3/P4 只解决：

```text
1. 容器运行产生的数据不要丢。
2. API、Milvus、etcd、minio 能启动。
3. 浏览器能打开 http://127.0.0.1:8000/app。
```

---

## 2. 本次不做什么

本阶段不做：

```text
不运行 rebuild_milvus.py。
不运行 rebuild_rxnorm_milvus.py。
不要求 SNOMED / RxNorm collection 已存在。
不要求 Analyze 标准化成功。
不跑 Benchmark 上传 60 条 cases。
不整理 .env.example。
不做 milvus-init 自动建库服务。
```

原因：

```text
P4 只验证“容器服务和前端页面是否能起来”。
Milvus collection 初始化属于 P5/P6。
业务链路验证属于 P7/P8。
```

---

## 3. P3：给 docker-compose.yml 加 volumes

### 3.1 为什么要加 volumes

如果不加 volumes：

```text
1. logs 只在容器里，容器删了日志就没了。
2. evaluation 输出可能只在容器里。
3. Milvus 数据可能随容器生命周期丢失。
4. embedding 模型缓存可能每次重建都重新下载。
5. backend/data 中的 CSV 数据无法稳定供建库脚本使用。
```

P3 的核心是把“运行数据”和“项目代码”分开。

---

### 3.2 推荐挂载清单

建议给 `api` 增加：

```yaml
volumes:
  - ./backend/logs:/app/backend/logs
  - ./backend/evaluation:/app/backend/evaluation
  - ./backend/data:/app/backend/data
  - ./model_cache/huggingface:/root/.cache/huggingface
```

含义：

```text
./backend/logs:/app/backend/logs
  保存 app.jsonl / pipeline.jsonl / dependency.jsonl / benchmark.jsonl / audit.jsonl / frontend.jsonl。

./backend/evaluation:/app/backend/evaluation
  保存 benchmark_results.json / error_analysis_report.json / fallback_candidate_promotions.json。

./backend/data:/app/backend/data
  提供 snomed_clinical.csv / rxnorm_clinical.csv / abbr_candidates.py。

./model_cache/huggingface:/root/.cache/huggingface
  保存 BAAI/bge-m3 模型缓存，避免反复下载。
```

建议给 `etcd` 增加：

```yaml
volumes:
  - etcd_data:/etcd
```

建议给 `minio` 增加：

```yaml
volumes:
  - minio_data:/minio_data
```

建议给 `milvus` 增加：

```yaml
volumes:
  - milvus_data:/var/lib/milvus
```

并在文件末尾增加：

```yaml
volumes:
  etcd_data:
  minio_data:
  milvus_data:
```

---

### 3.3 P3 推荐修改后的 compose 结构

只展示新增 volumes 相关部分：

```yaml
services:
  etcd:
    volumes:
      - etcd_data:/etcd

  minio:
    volumes:
      - minio_data:/minio_data

  milvus:
    volumes:
      - milvus_data:/var/lib/milvus

  api:
    volumes:
      - ./backend/logs:/app/backend/logs
      - ./backend/evaluation:/app/backend/evaluation
      - ./backend/data:/app/backend/data
      - ./model_cache/huggingface:/root/.cache/huggingface

volumes:
  etcd_data:
  minio_data:
  milvus_data:
```

---

### 3.4 P3 是否需要提前创建目录

建议创建：

```text
model_cache/huggingface
```

`backend/logs`、`backend/evaluation`、`backend/data` 当前项目已经存在。

执行命令：

```powershell
New-Item -ItemType Directory -Force -Path model_cache\huggingface
```

如果交给 Codex 执行，需要注意：

```text
只创建目录，不下载模型。
```

---

### 3.5 P3 验收标准

静态检查：

```text
docker-compose.yml 中 api.volumes 存在 logs / evaluation / data / huggingface cache。
docker-compose.yml 中 etcd.volumes 存在 etcd_data:/etcd。
docker-compose.yml 中 minio.volumes 存在 minio_data:/minio_data。
docker-compose.yml 中 milvus.volumes 存在 milvus_data:/var/lib/milvus。
docker-compose.yml 文件末尾存在 top-level volumes。
model_cache/huggingface 目录存在。
```

可执行检查：

```powershell
docker compose config
```

要求：

```text
compose 配置可解析。
不要求启动容器。
```

---

## 4. P4：本地 docker compose up，并确认 /app 能打开

P4 是第一次真正启动 Docker 服务。

### 4.1 启动前检查

先确认端口没有被占用：

```powershell
netstat -ano | findstr :8000
netstat -ano | findstr :19530
netstat -ano | findstr :9091
```

如果 8000 被本地 uvicorn 占用，需要先停掉本地后端。

如果 19530 被旧 Milvus 占用，需要先确认是不是旧容器或本地 Milvus。

注意：

```text
本阶段不要随便 taskkill 未确认的进程。
如果端口被占用，先把 PID 和进程名列出来，交给用户确认。
```

可查看：

```powershell
Get-Process -Id <PID>
```

---

### 4.2 启动命令

建议先构建并启动：

```powershell
docker compose up -d --build
```

说明：

```text
--build 确保 Dockerfile 的 COPY frontend ./frontend 生效。
-d 后台运行。
```

如果用户希望看实时启动日志，可以用：

```powershell
docker compose up --build
```

但 Codex 执行时更建议：

```powershell
docker compose up -d --build
docker compose logs --tail 120 api
docker compose logs --tail 120 milvus
```

---

### 4.3 容器状态检查

执行：

```powershell
docker compose ps
```

期待看到：

```text
medical-nlp-api      running
medical-nlp-milvus   running
medical-nlp-etcd     running
medical-nlp-minio    running
```

如果 api 退出：

```powershell
docker compose logs --tail 200 api
```

如果 milvus 退出：

```powershell
docker compose logs --tail 200 milvus
docker compose logs --tail 200 etcd
docker compose logs --tail 200 minio
```

---

### 4.4 页面验证

浏览器打开：

```text
http://127.0.0.1:8000/app
```

期待：

```text
能看到 Medical NLP V11 前端页面。
不是纯 JSON。
不是 Frontend not found。
不是 500。
```

API 根路径：

```text
http://127.0.0.1:8000/
```

预期可以返回：

```json
{
  "message": "Medical NLP Standardization API is running.",
  "docs": "/docs",
  "health": "/health"
}
```

健康检查：

```text
http://127.0.0.1:8000/health
```

预期：

```text
能返回健康检查 JSON。
```

---

### 4.5 P4 不要求 Analyze 成功

P4 只验证：

```text
前端页面能打开。
API 服务能启动。
Milvus 容器能启动。
```

此时还没有运行：

```text
rebuild_milvus.py
rebuild_rxnorm_milvus.py
```

所以 Milvus collection 可能还不存在。

如果在 P4 阶段点击 Analyze，可能出现：

```text
collection not found
标准化失败
500
```

这不属于 P4 失败。

真正 Analyze 业务验证放在：

```text
P7. Analyze 测试 SOB and CP。
```

---

## 5. P4 可能遇到的问题和处理

### 5.1 Docker daemon 权限问题

可能错误：

```text
permission denied while trying to connect to the docker API
```

处理：

```text
1. 确认 Docker Desktop 已启动。
2. 在用户自己的 PowerShell 中执行 docker compose 命令。
3. 如果 Codex 无权限连接 Docker API，则让用户手动执行 P4 命令。
```

### 5.2 镜像拉取失败

可能原因：

```text
网络无法访问 Docker Hub / quay.io。
```

处理：

```text
1. 记录失败镜像名称。
2. 不要乱换镜像版本。
3. 让用户确认网络或 Docker 镜像源。
```

涉及镜像：

```text
python:3.10-slim
quay.io/coreos/etcd:v3.5.18
minio/minio:RELEASE.2024-12-18T13-15-44Z
milvusdb/milvus:v2.5.4
```

### 5.3 API 容器启动后 /app 还是 Frontend not found

优先检查：

```powershell
docker compose exec api ls /app
docker compose exec api ls /app/frontend
docker compose exec api ls /app/frontend/index.html
```

如果 `/app/frontend` 不存在：

```text
说明镜像没有重新 build。
```

处理：

```powershell
docker compose up -d --build
```

### 5.4 端口 8000 被占用

如果：

```text
Bind for 0.0.0.0:8000 failed
```

处理：

```powershell
netstat -ano | findstr :8000
Get-Process -Id <PID>
```

确认后再决定是否停止旧进程。

### 5.5 Milvus 启动慢

Milvus 第一次启动可能慢。

处理：

```powershell
docker compose logs -f milvus
```

等待出现服务 ready 相关日志后再判断。

---

## 6. 建议交给 Codex 的执行范围

可以这样交给 Codex：

```text
请只执行 Docker P3/P4：

P3:
1. 修改 docker-compose.yml，给 api 挂载 backend/logs、backend/evaluation、backend/data、model_cache/huggingface。
2. 给 etcd 挂载 etcd_data:/etcd。
3. 给 minio 挂载 minio_data:/minio_data。
4. 给 milvus 挂载 milvus_data:/var/lib/milvus。
5. 在 compose 文件末尾增加 top-level volumes。
6. 创建 model_cache/huggingface 目录。
7. 执行 docker compose config 做静态校验。

P4:
1. 检查 8000 / 19530 / 9091 端口占用。
2. 如果端口冲突，先报告，不要擅自杀进程。
3. 执行 docker compose up -d --build。
4. 执行 docker compose ps。
5. 打开或请求 http://127.0.0.1:8000/app，确认前端页面能返回。
6. 请求 http://127.0.0.1:8000/health，确认 API 可访问。

不要做：
1. 不运行 rebuild_milvus.py。
2. 不运行 rebuild_rxnorm_milvus.py。
3. 不跑 Analyze。
4. 不跑 Benchmark。
5. 不修改业务代码。
6. 最后更新 交付版整理的改动.md。
```

---

## 7. P3/P4 成功标准

P3 成功：

```text
docker compose config 通过。
volume 配置存在。
model_cache/huggingface 目录存在。
```

P4 成功：

```text
docker compose ps 显示 api / milvus / etcd / minio 已启动。
http://127.0.0.1:8000/app 能打开前端页面。
http://127.0.0.1:8000/health 能返回。
```

P4 不要求：

```text
Analyze 成功。
标准化成功。
Milvus collection 存在。
Benchmark 成功。
```

---

## 8. P3/P4 完成后的下一步

完成 P3/P4 后，下一阶段才是：

```text
P5. 手动运行 rebuild_milvus.py 建 SNOMED collection。
P6. 手动运行 rebuild_rxnorm_milvus.py 建 RxNorm collection。
```

只有 P5/P6 完成后，P7 的 Analyze 标准化测试才有意义。

