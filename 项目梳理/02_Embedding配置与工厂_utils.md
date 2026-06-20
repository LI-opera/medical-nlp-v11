# Embedding 配置与工厂（决定"用哪个向量模型 + 怎么把它造出来"）

> 文件：`backend/utils/embedding_config.py`（40 行）+ `backend/utils/embedding_factory.py`（27 行）
> 入口函数：`create_embedding_model(config)`
> 衔接：上一篇的词典是"文字知识"。从这篇起进入**向量世界**——要把医学术语变成向量才能做相似度检索。这两个小文件就是"造向量模型"的地方，下一篇（StdService）会拿这个模型去连 Milvus 检索。

## 核心速记
> 1. **工厂模式**：业务代码不写死 `HuggingFaceEmbeddings(...)`，而是 `create_embedding_model(EmbeddingConfig())`。换模型/换供应商只改配置或加分支，不动业务代码——这是这两个文件唯一的存在理由。
> 2. **模型 = `BAAI/bge-m3`**：中英双语、检索稳，适合中英混的医学文本。
> 3. **`normalize_embeddings=True`**：向量归一化，配合建库时的 `COSINE` 度量，相似度语义对齐。这是最容易被追问的实现细节。
> 次要（trivia）：`@dataclass` 自动生成 `__init__`、`(str, Enum)` 限定选项、`trust_remote_code=True`——扫一眼。

## 这一段在解决什么

大白话：**两件事——"选哪个向量模型"和"怎么把它造出来"，拆成了两个文件。**

```text
embedding_config.py   = 配方单（写明：用 huggingface 的 bge-m3）
embedding_factory.py  = 工厂（拿着配方单，真正 new 出模型对象）
```

为什么要拆两个文件？因为"配置"和"创建"是两件事：配方单可以随便改，工厂照单生产。这样以后想换模型，改配方单就行。

## 核心1 · 工厂模式：为什么不直接 `new` 一个模型（骨架，必背）

最直白的写法是在用到的地方直接写死：

```python
# 反面：直接写死（StdService 里如果这么写）
self.embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-m3", ...)
```

问题：如果项目里有好几个地方都要 embedding，每处都写死一遍；将来想从 bge-m3 换成 OpenAI Embedding，**得改一堆地方**。

工厂模式把"怎么造"集中到一个函数：

```python
def create_embedding_model(config: EmbeddingConfig):
    if config.provider == EmbeddingProvider.HUGGINGFACE:
        return HuggingFaceEmbeddings(
            model_name=config.model_name,
            model_kwargs={"device": "cpu", "trust_remote_code": True},
            encode_kwargs={"normalize_embeddings": True},
        )
    raise ValueError(f"Unsupported embedding provider:{config.provider}")  # 不支持就报错
```

调用方只需要一句：

```python
embedding_model = create_embedding_model(EmbeddingConfig())   # 业务代码不关心是 bge 还是 openai
```

**为什么这是骨架**：解耦 + 易扩展。业务代码（StdService、建库工具）**不关心**底层用的是 BGE / E5 / GTE / OpenAI；将来要加新供应商，只在工厂里加一个 `if` 分支，调用方一行都不用动。`EmbeddingProvider` 用 `Enum` 把"供应商"限定成固定选项，传错直接报错，不会拼错字符串。

## 核心2 · 三个关键参数（证明你读过代码的实现细节）

```python
model_kwargs  = {"device": "cpu", "trust_remote_code": True}
encode_kwargs = {"normalize_embeddings": True}
```

逐个翻译：

- **`model_name="BAAI/bge-m3"`** —— 选 bge-m3 的理由：**中英双语 + 多语言、支持长文本、检索效果稳定**。医学文本常中英混（"患者有 SOB"），bge-m3 比纯英文模型更稳。
- **`normalize_embeddings=True`** —— 把每个向量**归一化成单位长度**。意义：归一化后，向量内积就等于余弦相似度。我**建 Milvus 库时用的度量是 `COSINE`**（`create_milvus_db.py` 里 `metric_type="COSINE"`），两边对齐，相似度语义一致、可比。**这是最值得主动讲的一个细节**——说明你知道"embedding 侧和向量库侧的度量必须配套"。
- **`device="cpu"`** —— 用 CPU 跑 embedding。简单但慢（见下方诚实局限）。
- 【次要】`trust_remote_code=True` —— 允许执行模型仓库里自带的代码（bge-m3 需要），了解即可。

## 数据快照：配置长什么样

```text
EmbeddingConfig() 默认展开 =
   provider   = "huggingface"        # EmbeddingProvider.HUGGINGFACE
   model_name = "BAAI/bge-m3"

create_embedding_model(EmbeddingConfig())
   → 一个 HuggingFaceEmbeddings 实例
   → .embed_query("chest pain") → [0.013, -0.027, ...]  归一化后的浮点向量
```

## 会被追问 / 诚实局限（★主动说）

- **`device` 写死 `"cpu"`**：有 GPU 也用不上。bge-m3 在 CPU 上做 embedding 偏慢，这是 **Benchmark 跑得慢的原因之一**（50 个 case 每个都要算 embedding）。
  → 面试这么说："当前固定 CPU 是开发期取舍，没绑定 GPU 环境。因为 `device` 已经收口在工厂里，生产化只要把它做成可配置（从 config / 环境变量读），切 GPU 不动业务代码——这正是工厂模式的好处。"
- **`model_name` 也是写死在 dataclass 默认值里**，没有从环境变量读。换模型要改代码。
  → "配置项应该外置到 `.env`，这是清晰的下一步。"
- **`provider` 目前只有 `HUGGINGFACE` 一个分支**，"工厂"现在只生产一种产品，有点"为扩展预留但还没用上"。
  → 诚实讲：这是**有意为未来留的扩展点**，不是过度设计——医学场景很可能要换成私有化/更强的 embedding，留好接口比到时重构便宜。
- **工厂层没有缓存/单例**：每次调 `create_embedding_model` 都会重新加载模型（几秒）。项目靠 **StdService 持有一个实例来复用**（下一篇讲），而不是在工厂里做单例。
  → "复用是在调用方（StdService）做的；如果有多处都要 embedding，更好的做法是工厂层加缓存。"
- **`trust_remote_code=True` 有安全含义**：会执行模型仓库的远程代码。可信模型没问题，但严格生产环境要评估。

## 面试怎么说

**合格版（30 秒）**：
> Embedding 这块我用工厂模式：`EmbeddingConfig` 是配置（默认 bge-m3 + huggingface），`create_embedding_model` 按配置生产模型实例。业务代码不写死具体模型，换模型只改配置或加分支。embedding 开了归一化，和我建库用的 COSINE 度量对齐。

**优秀版（1 分钟）**：
> 我把"用哪个向量模型"和"怎么创建它"拆成配置和工厂两个文件。选 bge-m3 是因为医学文本常中英混，它多语言、长文本、检索稳。一个我会主动讲的细节是：工厂里开了 `normalize_embeddings`，建 Milvus 库时度量用 COSINE，两边配套，保证相似度语义一致可比。工厂模式的价值是解耦——`device`、`model_name`、`provider` 都收口在这里，将来切 GPU、换成 OpenAI 或私有化 embedding，加个分支就行，业务代码不动。诚实说现在 `device=cpu`、`model_name` 写死是开发期取舍，也是 Benchmark 慢的原因之一，生产化第一步就是把这些配置外置。

## 易错点 / 面试问答

**Q：为什么选 bge-m3？** A：中英双语 + 多语言、支持长文本、检索效果稳。医学文本中英混，纯英文 embedding 不稳。

**Q：`normalize_embeddings=True` 有什么用？** A：把向量归一化成单位长度，使内积等于余弦相似度，和我建库用的 COSINE 度量对齐。不归一化的话相似度数值语义会和度量不匹配。

**Q：工厂模式解决了什么？** A：解耦和可扩展。把模型创建集中一处，调用方不依赖具体实现；换供应商加一个 `if` 分支即可。

**Q：为什么用 CPU？慢不慢？** A：开发期取舍，没绑定 GPU。确实慢，是 Benchmark 耗时的原因之一。`device` 已收口在工厂，生产改成可配置即可切 GPU。

**Q：模型每次都重新加载吗？** A：工厂本身不缓存，复用是在 StdService 持有单个实例来实现的（下一篇）。

## 一句话总结

> `utils/` 两个小文件用工厂模式解决"选哪个向量模型 + 怎么造"：`EmbeddingConfig` 是配方（默认 `BAAI/bge-m3`、huggingface），`create_embedding_model` 按配方生产实例并开启归一化，与建库的 COSINE 度量对齐。价值是把 `device/model_name/provider` 收口一处、解耦业务、便于换模型。局限是 `device=cpu` 和 `model_name` 写死、provider 只有一个分支、工厂层无缓存——都是"已留好扩展口、改配置即可"的开发期取舍。
