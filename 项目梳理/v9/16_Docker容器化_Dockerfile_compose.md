# Docker 容器化（把整个服务打包成一键启动的容器）

> 文件：`Dockerfile`（17 行）+ `docker-compose.yml`（16 行）
> 衔接：阶段五工程封装的收尾。服务（第 1~15 篇）都做好了，这一篇把它打包成镜像、配置好运行环境，让它能在任何机器上一键起。

## 核心速记
> 1. **分层缓存技巧**：先 COPY `requirements.txt` 装依赖，再 COPY 代码。改代码不用重装依赖——经典 Dockerfile 最佳实践。
> 2. **`host.docker.internal`**：容器里通过这个特殊域名连**宿主机**上的 Milvus（19530）。Milvus 没进容器，跑在宿主机。
> 3. **配置注入**：`env_file` 注入密钥，`environment` 覆盖 Milvus 地址（容器里不能用 127.0.0.1）。回扣第 4 篇 env 默认值。
> 次要（trivia）：`PYTHONUNBUFFERED=1`、`EXPOSE 8000`、`restart: unless-stopped`——扫一眼。

## 这一段在解决什么

大白话：**把"装 Python、装依赖、跑服务"这一串手动操作,固化成两个文件,一条命令就能在别的机器复现。**

```text
Dockerfile      = 怎么造这个镜像（装什么、怎么启动）
docker-compose  = 怎么跑这个镜像（端口、配置、连哪个 Milvus）
```

## 核心1 · Dockerfile 的分层缓存技巧（骨架，最该讲）

```dockerfile
FROM python:3.10-slim              # 瘦基础镜像
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt   # ① 先只拷依赖清单
RUN pip install -r requirements.txt                 # ② 装依赖
COPY backend ./backend                              # ③ 再拷代码
WORKDIR /app/backend
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**为什么先拷 requirements.txt、后拷代码（必背）**：Docker 是**分层构建 + 层缓存**的——每条指令是一层,只要这层的输入没变,就复用缓存不重跑。

- 如果把代码和依赖一起拷,那**改一行代码,pip install 就得重跑一遍**（装 torch/transformers 几分钟）。
- 拆开后:`requirements.txt` 没变 → pip install 那层直接用缓存;**只有改依赖时才重装**。改代码只重跑最后那层（秒级）。

这是 Dockerfile 的经典优化,体现你懂构建效率。

【次要】`python:3.10-slim` 瘦镜像减体积;`PYTHONUNBUFFERED=1` 让日志实时刷出（不缓冲,方便看 log）;`--host 0.0.0.0` 让容器外能访问（不是 127.0.0.1）。

## 核心2 · `host.docker.internal`：容器怎么连宿主机的 Milvus（关键设计）

```yaml
environment:
  MILVUS_URI: http://host.docker.internal:19530
  MILVUS_COLLECTION_NAME: concepts_only_name
```

**核心认知:Milvus 没被容器化,它跑在你的宿主机上(19530)。** API 在容器里,要连容器**外面**宿主机的 Milvus。

问题:容器内部的 `127.0.0.1` 指的是**容器自己**,不是宿主机。所以代码里默认的 `http://127.0.0.1:19530`(第 4 篇)在容器里连不到 Milvus。

解法:Docker 提供一个特殊域名 **`host.docker.internal`**,在容器里它**指向宿主机**。所以 compose 用 `environment` 把 `MILVUS_URI` 覆盖成它,容器就能连到宿主机的 Milvus 了。

```text
宿主机
  └── Milvus :19530 ◄─────┐
                          │ host.docker.internal:19530
Docker 容器               │
  └── FastAPI :8000 ──────┘
```

这正好回扣第 4 篇:`MILVUS_URI` 走 env、带默认值——**本地直接用 127.0.0.1,容器用 environment 覆盖成 host.docker.internal,同一份代码两种环境**。这就是 env 配置化的价值。

## 核心3 · compose 的配置注入

```yaml
ports:    ["8000:8000"]          # 宿主机8000 → 容器8000
env_file: [backend/.env]          # 注入 DEEPSEEK_API_KEY 等密钥
environment:                      # 覆盖 Milvus 地址（优先级高于 env_file）
  MILVUS_URI: http://host.docker.internal:19530
restart: unless-stopped           # 挂了自动重启（除非手动停）
```

`env_file` 把 `.env` 里的密钥注入容器,`environment` 再覆盖 Milvus 相关——两者配合,密钥从文件来、环境相关配置在 compose 里定。

## 数据快照：一键启动

```text
$ docker compose up --build
  → 构建镜像（装依赖、拷代码）
  → 起容器 medical-nlp-api，映射 8000 端口
  → 注入 .env 密钥 + 覆盖 MILVUS_URI=host.docker.internal
  → uvicorn 起 FastAPI
访问 http://localhost:8000/docs 即可
（前提：宿主机已跑着 Milvus 并建好库）
```

## 会被追问 / 诚实局限（★主动说）

- **只容器化了 API,Milvus 没进容器**:所谓"一键部署"是半成品——还得**宿主机先装好 Milvus 并跑 `create_milvus_db.py` 建好库**,API 容器才能用。
  → 面试这么说："当前只把 API 容器化,Milvus 依赖宿主机现成实例,通过 host.docker.internal 连。更完整的做法是 compose 里再加一个 Milvus 服务,用 depends_on 编排,真正一键起全套——这是我清楚的下一步。"
- **`.env` 密钥可能被打进镜像**:`COPY backend ./backend` 会把整个 backend 目录(**包括 `backend/.env`**)拷进镜像层。密钥被固化进镜像,有泄露风险。
  → "应该加 `.dockerignore` 排除 `.env`,密钥只在运行时通过 env_file/environment 注入,不进镜像。这是个安全隐患,我会修。"
- **模型权重没预装进镜像**:NER 模型、bge-m3 是**首次运行容器时才从 HuggingFace 联网下载**——首启慢、且依赖网络。生产应预下载进镜像或挂载卷。
- **镜像可能很大**:torch + transformers 几个 GB,虽然用了 slim 基础镜像,依赖本身巨大。可考虑多阶段构建、CPU 版 torch 精简。
- **`host.docker.internal` 可移植性**:Docker Desktop(Mac/Win)自带,但 **Linux 上默认不一定可用**,要在 compose 里加 `extra_hosts` 映射。换部署环境可能踩坑。
- **没有 healthcheck、没用非 root 用户**:生产化的健壮性/安全项还缺。

## 面试怎么说

**合格版（30 秒）**：
> 用 Dockerfile + compose 容器化 API:Dockerfile 先拷 requirements 装依赖再拷代码,利用层缓存让改代码不用重装依赖;compose 配端口、注入 .env 密钥,并用 environment 把 Milvus 地址覆盖成 host.docker.internal,让容器连宿主机的 Milvus。

**优秀版（1 分钟）**：
> 容器化我重点处理两件事:构建效率和环境配置。Dockerfile 把 requirements.txt 和代码分开拷——依赖层能缓存,改代码只重跑最后一层,不用每次重装 torch。网络上,Milvus 没进容器、跑在宿主机,容器内 127.0.0.1 指向自己连不到,所以用 Docker 的 host.docker.internal 域名指向宿主机,通过 compose 的 environment 覆盖 MILVUS_URI——这正好用上了我代码里 env 带默认值的设计,本地用默认、容器用覆盖。诚实说几个局限:只容器化了 API、Milvus 靠宿主机,不是真正一键全套;COPY 会把 .env 打进镜像有泄露风险,应该加 .dockerignore;模型权重首次要联网下载。这些都是我清楚的生产化待办。

## 易错点 / 面试问答

**Q：为什么先拷 requirements 再拷代码？** A：利用 Docker 层缓存。依赖单独一层,代码没改时复用缓存,不用每次重装；改代码只重跑最后一层。

**Q：host.docker.internal 是什么？** A：Docker 提供的特殊域名,在容器里指向宿主机。因为 Milvus 跑在宿主机、不在容器里,容器用它来连。

**Q：为什么 --host 0.0.0.0 不是 127.0.0.1？** A：容器内 127.0.0.1 只能容器自己访问,0.0.0.0 才能让容器外（宿主机端口映射）访问到服务。

**Q：这套部署是真正一键吗？** A：不完全。只容器化了 API,Milvus 还得宿主机先装好建好库。更完整应该 compose 里也编排 Milvus。

**Q：有什么安全隐患？** A：COPY 把 backend/.env 打进了镜像,密钥可能泄露,应加 .dockerignore 排除,只在运行时注入。

## 一句话总结

> Docker 容器化把服务打包成一键启动镜像:Dockerfile 用"先依赖后代码"的分层缓存技巧加速构建,compose 配端口、注入 .env 密钥、用 environment 把 Milvus 地址覆盖成 host.docker.internal 连宿主机 Milvus（回扣 env 配置化）。局限是只容器化 API（Milvus 靠宿主机、非真一键）、.env 可能被打进镜像（应 .dockerignore）、模型首启要联网下载——都是清晰的生产化待办。
