# FastAPI 入口与懒加载（项目的大门 + 模型按需启动）

> 文件：`backend/api/main.py`（185 行）+ `backend/api/schemas.py`（49 行）
> 入口函数：`expand_abbreviation_simple()`（主业务）、`get_service()`（懒加载）
> 衔接：这是整条链路的**第 0 步**——HTTP 请求从这里进来，校验后交给 `ABBRService`（下一篇讲），结果再从这里出去。

## 核心速记
> 1. **懒加载**：`service = None`，模型不在启动时加载，**第一次请求**才 `ABBRService()`。这是本篇最重要的一个设计。
> 2. **5 个路由**：`/`、`/health`、`/benchmark/summary`、`/error-analysis/summary`、`POST /expand/simple`。
> 3. **Pydantic 把关**：进来必须是 `{text:"..."}`，出去固定 `{success, expanded_text, mappings}`。
> 次要（trivia）：`sys.path.append` 改导入路径、两个 summary 接口只是读 JSON 文件——扫一眼即可。

## 这一段在解决什么

把整个医学 NLP pipeline 包成一个能用 HTTP 调用的后端。大白话：**别人发一句临床文本过来，这里接住、做基本检查、丢给大脑处理、再把结果包成 JSON 还回去。**

```text
HTTP 请求 {text:"Patient has SOB and CP."}
   ↓ FastAPI 接住 + Pydantic 校验
   ↓ get_service() 拿到 ABBRService（首次才真正创建）
   ↓ service.expand_verify_with_retry(...)   ← 大脑在下一篇
   ↓ 包成 SimpleExpandResponse
HTTP 响应 {success, expanded_text, mappings}
```

## 核心1 · 懒加载（lazy loading）：为什么模型不在启动时加载

先翻译：**"懒加载" = 用到的时候才创建，不用就不碰。**

```python
service = None              # 启动时只是一个空壳，什么都没加载

def get_service():
    global service
    if service is None:     # 第一次进来时 service 还是 None
        service = ABBRService()   # ← 这一刻才真正加载模型
    return service          # 之后所有请求复用同一个实例
```

**为什么这么设计（骨架，必背）**：`ABBRService()` 一旦创建，会连环加载一堆重对象——HuggingFace 医学 NER 模型、bge-m3 embedding 模型、连 Milvus 向量库、初始化 DeepSeek 客户端。这些加载要几十秒。如果放在启动时：

- API 启动会卡很久，`/health` 都迟迟不通；
- 万一只是想看看 `/benchmark/summary`（读个 JSON），根本用不到模型，却被迫全加载。

所以把这些**推迟到第一次真正需要扩写时**。代价是"第一次请求很慢（冷启动），后面就快了"。

**真实数据：加载链**（首次 `/expand/simple` 才触发）

```text
get_service() → ABBRService.__init__()
  → ChatDeepSeek 初始化
  → MedicalStandardizer → NERService(加载 HuggingFace NER)
  → MedicalRetriever → StdService(加载 bge-m3 + 连 Milvus + load_collection)
  → ABBVerifier / ABBRReflectionService / 候选三件套 初始化
```

## 核心2 · 主路由 `/expand/simple`：请求怎么进、结果怎么出

```python
@app.post("/expand/simple", response_model=SimpleExpandResponse)
def expand_abbreviation_simple(request: ExpandRequest):
    abbr_service = get_service()                      # 懒加载拿实例
    result = abbr_service.expand_verify_with_retry(   # 丢给大脑，下一篇讲
        text=request.text, max_retries=2
    )
    final_result = result.get("final_result", {})
    return {                                           # 只挑 3 个字段返回
        "success": result.get("success", False),
        "expanded_text": final_result.get("expanded_text", request.text),
        "mappings": final_result.get("mappings", [])
    }
```

**为什么 `response_model=SimpleExpandResponse`**：让 FastAPI 强制响应只含这 3 个字段。`ABBRService` 内部其实返回了一大坨（`attempts`、`standardization`、`verification`…），这里**故意只暴露精简版**给调用方。

**真实数据：一次请求的进/出**

```text
【入】 POST /expand/simple
        body: { "text": "Patient has SOB and CP." }

【出】 200 OK
        {
          "success": true,
          "expanded_text": "Patient has shortness of breath and chest pain.",
          "mappings": [
            {"abbreviation":"SOB","expansion":"shortness of breath","source":"candidate"},
            {"abbreviation":"CP","expansion":"chest pain","source":"candidate"}
          ]
        }
```

## 核心3 · Pydantic 校验：进出都有固定形状

`schemas.py` 用 Pydantic 模型规定请求/响应的"形状"，FastAPI 自动校验+生成文档。

```python
class ExpandRequest(BaseModel):
    text: str = Field(..., description="输入的临床文本")   # ... = 必填

class SimpleExpandResponse(BaseModel):
    success: bool
    expanded_text: str
    mappings: list[dict]
```

翻译：**进来的 JSON 必须有 `text` 字段且是字符串**，否则 FastAPI 直接返 422 错误，根本进不到业务逻辑。**出去的必须正好是 `success/expanded_text/mappings`**。这就是"接口契约"——调用方不用猜格式。

## 其余路由（次要，一行带过）

【次要】`GET /` 返回欢迎信息；`GET /health` 只查 API 活没活（注释里写明**不查 Milvus/LLM**）；`GET /benchmark/summary` 和 `/error-analysis/summary` 只是**读两个静态 JSON 文件**（benchmark/error_analysis 的结果）返回，不跑模型——这两个对应第 6 篇评估系统。

## 会被追问 / 诚实局限（★主动说）

- **完整版 `/expand` 接口被注释掉了**（`main.py` 141–155 行）。它本来会返回 `verification` 和 `attempts`（调试用）。现在线上只有精简版 `/expand/simple`。
  → 面试这么说："我保留了一个完整调试接口的代码但默认关掉，线上只暴露精简响应，避免把内部校验细节泄露给调用方——这是有意的接口收敛。"
- **没有错误处理 / try-except**：如果 DeepSeek 超时、Milvus 连不上，请求会直接抛异常 500，没有优雅降级。
  → 面试这么说："当前是 MVP，异常直接冒泡；生产化第一步就是加超时、重试和统一错误响应。"
- **全局单例 `service`，没考虑并发安全**：多个请求同时进来都共享同一个实例。当前够用（FastAPI 单进程 + 模型只读），但高并发下 Milvus/LLM 客户端是否线程安全没验证。
  → 面试这么说："单实例复用是为了不重复加载模型；并发安全我评估过——调用都是无状态只读，风险可控，真要扩展会上多 worker + 连接池。"
- **summary 接口读的是静态 JSON**：`/benchmark/summary` 不是实时跑评估，是读上一次 `run_benchmark.py` 留下的文件。文件不存在就返回全 0。
  → 这本身合理（评估是离线的），但要能讲清"为什么评估不放在线上实时跑"（慢、费钱、不该占用线上资源）。
- **`max_retries=2` 写死在路由里**：调用方改不了重试次数。

## 面试怎么说

**合格版（30 秒）**：
> 入口是 FastAPI。我用懒加载——`service=None`，第一次 `/expand/simple` 请求才实例化 `ABBRService`，避免启动就加载 NER、embedding、Milvus 这些重对象。请求体和响应都用 Pydantic 模型约束，线上只暴露 `success/expanded_text/mappings` 三个字段。

**优秀版（1 分钟）**：
> 入口层我重点处理两件事：启动性能和接口契约。重对象（HuggingFace NER、bge-m3、Milvus 连接）加载要几十秒，所以我用懒加载哨兵 `service=None`，推迟到首个扩写请求再创建，之后全局复用同一实例；代价是首请求冷启动慢，但 `/health` 和评估查询接口不受影响。响应我做了收敛——内部其实有 `verification`、`attempts` 等调试信息，但线上 `/expand/simple` 只返精简三字段，完整调试版 `/expand` 我保留代码但默认注释关闭。诚实说当前还缺统一异常处理和并发压测，是我清楚的下一步。

## 易错点 / 面试问答

**Q：懒加载的代价是什么？** A：第一次请求很慢（冷启动，要加载所有模型），之后才快。生产可以加一个"预热"请求或启动钩子提前触发。

**Q：为什么 `/health` 不检查 Milvus 和 LLM？** A：故意的。`/health` 只确认 API 进程活着（给负载均衡/k8s 探活用），不触发懒加载，否则探活就把模型全加载了。代码注释里明确写了这点。

**Q：`response_model` 有什么用？** A：FastAPI 用它做两件事——校验响应形状、自动生成 `/docs` 接口文档。也是一道"只暴露该暴露的字段"的安全闸。

**Q：请求格式错了会怎样？** A：Pydantic 校验不过，FastAPI 自动返 422，根本进不到业务函数。

## 一句话总结

> 入口层用 FastAPI + Pydantic：懒加载（`service=None`，首请求才创建 `ABBRService`）解决"模型加载慢、不该启动就加载"的问题，`response_model` 把响应收敛成 `success/expanded_text/mappings` 三字段。它只负责接住、校验、转交、包装，真正的活在下一篇的 `ABBRService`。局限是无异常处理、`max_retries` 写死、完整调试接口被注释——都是可讲成"有意收敛 + 清晰的下一步"的 MVP 取舍。
