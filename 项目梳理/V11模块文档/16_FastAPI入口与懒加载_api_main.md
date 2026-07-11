# FastAPI 入口与懒加载 —— api/main.py · V11

> 文件:`backend/api/main.py`、`backend/api/schemas.py`
> 衔接:第 14/15 篇已经讲完内部主状态机。本篇从外部请求视角看:HTTP 请求怎么进入系统、什么时候创建 `ABBRService`、API 如何把内部复杂结果裁剪成前端/调用方更容易用的简洁 JSON。
> **V11 必看定位**:当前真正启用的主接口是 `POST /expand/simple`。注释掉的 `/expand` 是旧完整调试版,不是当前运行接口。`/health` 也只是 API 存活检查,不会提前初始化 Milvus 或 LLM。

## 核心速记

> 1. **主入口**:`POST /expand/simple` 接收 `{text}`,调用 `ABBRService.expand_verify_with_retry(text, max_retries=2)`,返回 `success / expanded_text / mappings / standardized_entities`。
> 2. **懒加载**:`service = None`;第一次请求 `/expand/simple` 时才 `ABBRService()`。这避免服务启动时立刻加载 HuggingFace 模型、连接 Milvus、初始化 LLM。
> 3. **API 做裁剪**:内部 `final_result` 很复杂;API 只把 `chosen_concept` 非空的 mapping 转成 `standardized_entities` 输出。
> 次要(trivia):`GET /benchmark/summary` 和 `GET /error-analysis/summary` 只是读 JSON 文件,不跑评估。

## 这一段在解决什么

大白话:**别人怎么调用你的 medical-nlp 后端?**

最核心请求:

```http
POST /expand/simple
Content-Type: application/json

{
  "text": "The patient denies SOB but reports CP."
}
```

返回简洁版:

```json
{
  "success": true,
  "expanded_text": "The patient denies shortness of breath but reports chest pain.",
  "mappings": [
    {"abbreviation": "SOB", "expansion": "shortness of breath"},
    {"abbreviation": "CP", "expansion": "chest pain"}
  ],
  "standardized_entities": [
    {
      "abbreviation": "CP",
      "expansion": "chest pain",
      "concept_id": "...",
      "concept_name": "Chest pain"
    }
  ]
}
```

注意:上面是结构示例,真实 concept_id / score 取决于 Milvus 当前库。

## 核心1 · 启动入口:FastAPI app

`main.py` 创建应用:

```python
app = FastAPI(
    title="Medical NLP Standardization API",
    description="医学缩写扩写、术语标准化、Verification 与 Reflection API",
    version="0.1.0"
)
```

Dockerfile 里的启动命令:

```dockerfile
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

所以运行时:

```text
uvicorn
  ↓
加载 api.main:app
  ↓
FastAPI 注册路由
```

这时还不会创建 `ABBRService`,因为 service 是懒加载。

## 核心2 · sys.path 处理:让 backend 内模块能被导入

文件开头:

```python
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))
```

目的:

```text
把 backend 目录加入 Python 模块搜索路径
```

这样下面这些导入才能工作:

```python
from api.schemas import ...
from services.abbr_service import ABBRService
```

这是这个项目当前的路径处理方式。更标准的方式可以是包安装/模块化运行,但当前写法直接、好理解。

## 核心3 · 懒加载 get_service()

代码:

```python
service = None

def get_service():
    global service

    if service is None:
        service = ABBRService()

    return service
```

含义:

```text
服务启动时:
  service = None
  不加载模型、不连 Milvus、不初始化 LLM

第一次 /expand/simple 请求:
  get_service()
  service is None → 创建 ABBRService()

后续请求:
  复用同一个 ABBRService 实例
```

为什么需要懒加载?

因为 `ABBRService.__init__()` 会创建:

```text
MedicalStandardizer / NERService
MedicalRetriever / StdService / MilvusClient
ABBVerifier
FallbackRetriever
CoverageEvaluator
Embedding model
LLM client
```

这些对象可能很重。懒加载能让 API 进程更快启动,也让 `/health` 不因为模型/Milvus 暂时不可用而失败。

## 核心4 · /health 只检查 API 存活

路由:

```python
@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "Medical NLP Standardization API",
        "version": "0.1.0",
        "checks": {"api": "ok"},
        "note": "This endpoint only checks whether the API server is running. Milvus and LLM are initialized on first request."
    }
```

重点:

```text
/health 不会调用 get_service()
/health 不会检查 Milvus
/health 不会检查 DEEPSEEK_API_KEY
/health 不会加载 HuggingFace 模型
```

所以:

```text
/health = API 进程活着
不等于 /expand/simple 一定能跑通
```

面试/部署时这点要主动说,否则容易误以为 health 是完整依赖探测。

## 核心5 · Pydantic schema:请求和响应长什么样

请求:

```python
class ExpandRequest(BaseModel):
    text: str = Field(..., description="输入的临床文本")
```

也就是说请求 body 必须有:

```json
{"text": "..."}
```

简洁响应:

```python
class SimpleExpandResponse(BaseModel):
    success: bool
    expanded_text: str
    mappings: list[dict]
    standardized_entities: list[dict] = []
```

完整调试响应 schema 也还在:

```python
class ExpandResponse(BaseModel):
    success: bool
    expanded_text: str
    mappings: list[dict]
    verification: dict | None = None
    attempts: list[dict] | None = None
```

但对应的 `/expand` 路由被注释掉了。

## 核心6 · 当前主接口 /expand/simple

代码:

```python
@app.post("/expand/simple", response_model=SimpleExpandResponse)
def expand_abbreviation_simple(request: ExpandRequest):
    abbr_service = get_service()

    result = abbr_service.expand_verify_with_retry(
        text=request.text,
        max_retries=2
    )

    final_result = result.get("final_result", {}) or {}
    ...
    return {...}
```

流程:

```text
HTTP JSON
  ↓
FastAPI / Pydantic 校验成 ExpandRequest
  ↓
get_service() 懒加载 ABBRService
  ↓
expand_verify_with_retry(text, max_retries=2)
  ↓
取 final_result
  ↓
裁剪成 SimpleExpandResponse
```

注意:

```text
max_retries=2 写死在 API 层
调用方不能通过请求参数修改
```

虽然第 14 篇说过,当前 V11 的 `max_retries` 语义已不像旧版整句多轮重写那么强,但这个参数仍被传入。

## 核心7 · standardized_entities 怎么生成

API 不直接返回内部完整 `mapping_standardizations`,而是裁剪出标准化成功的实体:

```python
standardized_entities = []
for ms in final_result.get("mapping_standardizations", []):
    top = ms.get("chosen_concept")
    if not top:
        continue
    standardized_entities.append({
        "abbreviation": ms.get("abbreviation"),
        "expansion": ms.get("expansion"),
        "concept_id": top.get("concept_id"),
        "concept_name": top.get("concept_name"),
        "concept_code": top.get("concept_code"),
        "domain_id": top.get("domain_id"),
        "score": top.get("score"),
    })
```

含义:

```text
只有 chosen_concept 非空的 mapping 才进入 standardized_entities
```

也就是说:

```text
CODED
  chosen_concept 有值
  → 输出到 standardized_entities

WITHHELD
  chosen_concept = None
  → 不输出 standardized_entities
  但 mappings 里仍可能有 expansion
```

这和第 14 篇的"扩写和编码解耦"完全对应。

## 核心8 · API 返回的 mappings 和 standardized_entities 区别

`mappings` 来自:

```python
final_result.get("mappings", [])
```

它表示:

```text
哪些缩写被扩成了什么
```

`standardized_entities` 表示:

```text
哪些扩写同时拿到了忠实标准概念
```

所以可能出现:

```json
{
  "mappings": [
    {"abbreviation": "XYZ", "expansion": "some expansion"}
  ],
  "standardized_entities": []
}
```

这不是矛盾。它说明:

```text
扩写被接受
但标准概念编码被 WITHHELD
```

## 核心9 · /benchmark/summary 和 /error-analysis/summary

### /benchmark/summary

代码:

```python
benchmark_path = BACKEND_DIR / "evaluation" / "benchmark_results.json"
```

如果文件不存在:

```json
{
  "total_cases": 0,
  "correct": 0,
  "accuracy": 0.0,
  "category_stats": {}
}
```

如果存在,读取 JSON:

```json
{
  "total_cases": data.get("total", 0),
  "correct": data.get("correct", 0),
  "accuracy": data.get("accuracy", 0.0),
  "category_stats": data.get("category_stats", {})
}
```

### /error-analysis/summary

读取:

```python
backend/evaluation/error_analysis_report.json
```

返回:

```json
{
  "benchmark_summary": {...},
  "failed_summary": {...}
}
```

重点:

```text
这两个接口只是读现有报告文件
不会现场跑 benchmark
不会现场跑 error analysis
```

## 路由总览

```text
GET /
  返回 API running + docs/health 路径

GET /health
  只检查 API 进程

GET /benchmark/summary
  读取 evaluation/benchmark_results.json

GET /error-analysis/summary
  读取 evaluation/error_analysis_report.json

POST /expand/simple
  当前主功能接口
  调 ABBRService.expand_verify_with_retry()

POST /expand
  旧完整调试版,当前注释掉
```

## 数据流总图

```text
client
  ↓ POST /expand/simple {"text": "..."}
FastAPI
  ↓ Pydantic ExpandRequest
get_service()
  ↓ 第一次请求才 ABBRService()
ABBRService.expand_verify_with_retry()
  ↓
result.final_result
  ↓
API 裁剪:
  success
  expanded_text
  mappings
  standardized_entities(chosen_concept 非空)
  ↓
SimpleExpandResponse
```

## 其余细节(次要,一行带过)

【次要】`root()` 返回 docs 和 health 位置;`response_model` 会让 FastAPI 按 schema 输出;`with open(..., encoding="utf-8")` 读取中文 JSON;`ExpandResponse` 虽然还在 schema 里,但当前没有启用对应路由。

## 死代码 / 盲肠提醒

- 注释掉的 `/expand` 是旧完整调试版接口,当前不会注册。
- `ExpandResponse` 当前主要服务注释掉的 `/expand`,属于保留 schema。
- `import os` 在 `main.py` 当前没有实际使用。
- `/health` 的 note 写得很诚实:Milvus 和 LLM 首次请求才初始化。
- `standardized_entities` 注释写"SNOMED 概念",但 V11 多源下也可能是 RxNorm chosen_concept,文案应改成"标准概念"更准确。

## 优化方向(更好 / 更稳)

1. **增加 deep health**:新增 `/health/deep` 或 `/ready`,显式检查 env、Milvus collection、embedding、LLM。
2. **暴露调试接口但受控**:可以恢复 `/expand` 为 debug endpoint,加开关或鉴权,方便查看 attempts/mapping_states。
3. **max_retries 参数化**:允许请求传入或配置控制,但需要限制范围。
4. **返回 mapping_states**:简洁接口可选返回状态解释,帮助调用方理解 WITHHELD/NOT_EXPANDED。
5. **修正 SNOMED 文案**:`standardized_entities` 可能来自 RxNorm,不应只写 SNOMED。
6. **线程安全考虑**:全局单例 `service` 简单好用,但多 worker / 多线程下可进一步评估模型客户端和 MilvusClient 的并发行为。
7. **启动预热选项**:可通过 env 控制是否启动时预加载 service,适合生产 ready check。

## 会被追问 / 诚实局限(主动说)

- **/health 不代表依赖可用**:只证明 API 活着。
- **首次请求可能慢**:因为懒加载会加载 NER/embedding/Milvus/LLM。
- **全局单例简单但粗糙**:适合原型,生产要考虑并发、worker、多进程资源。
- **简洁接口隐藏了内部状态**:调用方只看 standardized_entities 可能不知道某个扩写为何 WITHHELD。
- **报告接口不实时计算**:只是读已有 JSON 文件。

## 面试怎么说

**合格版(30 秒)**:
> FastAPI 当前主接口是 `/expand/simple`。它接收 `text`,第一次请求时通过 `get_service()` 懒加载 `ABBRService`,然后调用 `expand_verify_with_retry`。内部结果很复杂,API 只返回 success、expanded_text、mappings 和 chosen_concept 非空的 standardized_entities。`/health` 只检查 API 存活,不会检查 Milvus 和 LLM。

**优秀版(1 分钟)**:
> 我把 API 层设计成很薄的门面。FastAPI 负责请求校验和响应裁剪,真正业务都在 ABBRService。为了避免服务启动时就加载 HuggingFace 模型、Milvus 和 LLM,我用全局 `service=None` 做懒加载,第一次 `/expand/simple` 请求才初始化,后续复用。返回时我刻意把内部 `final_result` 裁剪掉,只把扩写结果和真正有 chosen_concept 的标准化实体给调用方。这样 `mappings` 和 `standardized_entities` 是分开的:前者说明扩写了什么,后者说明哪些扩写成功编码。诚实说,`/health` 只是 shallow health,首次请求会慢,全局单例也需要生产并发评估。

## 易错点 / 面试问答

**Q:当前主接口是 `/expand` 还是 `/expand/simple`?**  
A:当前启用的是 `/expand/simple`;`/expand` 是注释掉的旧完整调试版。

**Q:/health 会检查 Milvus 吗?**  
A:不会。它只检查 API 进程,Milvus 和 LLM 是首次请求才初始化。

**Q:standardized_entities 为什么可能比 mappings 少?**  
A:mappings 表示扩写成功;standardized_entities 只包含 chosen_concept 非空的编码成功项。WITHHELD 会有 mapping,但没有 standardized_entity。

**Q:为什么要懒加载?**  
A:避免启动时加载重模型和外部依赖,让 API 更快启动;代价是首次请求较慢。

**Q:benchmark summary 会重新跑 benchmark 吗?**  
A:不会,只是读取 `backend/evaluation/benchmark_results.json`。

**Q:如果想看 attempts/mapping_states 怎么办?**  
A:当前简洁接口不返回这些。可以恢复/新增 debug endpoint,或在 simple 接口加 debug 参数。

## 一句话总结

> `api/main.py` 是 V11 后端的薄门面:FastAPI 负责路由、Pydantic 校验、懒加载 `ABBRService` 和响应裁剪;核心业务在 `expand_verify_with_retry()`。当前主接口 `/expand/simple` 返回扩写文本、mappings 和真正有 chosen_concept 的 standardized_entities。`/health` 是浅检查,报告接口只读已有 JSON。它适合作为原型 API 入口,后续生产化可补 deep health、debug endpoint、并发与预热配置。
