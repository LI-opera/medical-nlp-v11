# Embedding 配置与工厂(把"用哪个向量模型"和"怎么用"解耦)· V11

> 文件:`backend/utils/embedding_config.py`(声明配置)+ `backend/utils/embedding_factory.py`(按配置造模型)
> 衔接:**它把文本变成向量**,是 RAG 检索的发动机。上游 `StdService`(第 05 篇)用它把 query 编码后丢进 Milvus 搜;离线建库工具(第 04 篇)用它把几十万个 SNOMED/RxNorm 概念名编码后灌库。没有它,检索这条链就动不了。
> **看点**:这是项目里 "config + factory" 设计模式的**第一处**,后面 LLM 工厂(第 03 篇)是照它复制的。

## 核心速记
> 1. **config / factory 分离**:`EmbeddingConfig` 只**声明**"用 huggingface 的 bge-m3";`create_embedding_model(config)` 负责**真正加载**。业务代码只认 config,不碰加载细节——换模型只改一行 config,调用方零改动。必背这个"解耦"动机。
> 2. **模型 = BAAI/bge-m3**:多语言、长文本、检索向量强。`normalize_embeddings=True`(归一化,配合 Milvus 的余弦/内积度量)。
> 3. **device 自动 cuda/cpu**:`torch.cuda.is_available()` 在则用 GPU,否则 CPU——同一份代码本机/服务器都能跑(V11 运行环境补丁之一)。
> 次要(trivia):`EmbeddingProvider` 枚举目前只有 `HUGGINGFACE` 一个值;`trust_remote_code=True`。

## 这一段在解决什么

大白话:**把一段文字变成一串数字(向量),好让机器算"哪两段意思最像"。**

```text
"chest pain"  →  embed  →  [0.013, -0.082, ... ]  (bge-m3 输出的 1024 维向量)
"aspirin"     →  embed  →  [-0.041, 0.067, ... ]
```

有了向量,Milvus 才能算"query 向量"和"库里几十万个概念向量"谁最近——这就是向量检索的本质(第 05/06 篇)。本模块只负责"造出这台编码器",不负责检索。

## 核心1 · config + factory:为什么要拆成两个文件(必背)

```python
# embedding_config.py —— 只声明,不加载
class EmbeddingProvider(str, Enum):
    HUGGINGFACE = "huggingface"

@dataclass
class EmbeddingConfig:
    provider: EmbeddingProvider = EmbeddingProvider.HUGGINGFACE
    model_name: str = "BAAI/bge-m3"
```

```python
# embedding_factory.py —— 按 config 真正造模型
def create_embedding_model(config: EmbeddingConfig):
    if config.provider == EmbeddingProvider.HUGGINGFACE:
        return HuggingFaceEmbeddings(
            model_name=config.model_name,
            model_kwargs={"device": "cuda" if torch.cuda.is_available() else "cpu",
                          "trust_remote_code": True},
            encode_kwargs={"normalize_embeddings": True},   # 归一化
        )
    raise ValueError(f"Unsupported embedding provider:{config.provider}")
```

**为什么拆**:
- 调用方(StdService)只写 `create_embedding_model(EmbeddingConfig())`,**不需要知道**是 HuggingFace 还是别的、device 怎么选、要不要归一化;
- 想换模型(比如试 `bge-large` 或医学专用 embedding)= 只改 config 的 `model_name`,**所有用到的地方零改动**;
- 想接新平台(比如 OpenAI embedding)= 在 factory 加一个 `elif provider == ...` 分支,不动业务。

这就是"**配置驱动 + 工厂模式**":把"选什么"(易变)和"怎么用"(稳定)隔开。面试点:同一套思路 V11 又用在 LLM 上(`llm_config`/`llm_factory`,第 03 篇),所以才能"verify 换个模型只改一行"。

## 核心2 · 为什么是 bge-m3 + 归一化

- **bge-m3**:开源检索向量里的强基线,支持多语言 + 长文本;临床术语短、英文为主,它够用且免费、可本地跑(不外发数据,合规友好)。
- **`normalize_embeddings=True`**:把向量归一化到单位长度。归一化后"余弦相似度"等价于"内积",**必须和 Milvus 建库时的距离度量对齐**(本项目用 COSINE)——否则分数语义会错(第 05 篇会讲 score=round(distance,4) 的坑)。

## 数据快照

```text
输入:任意文本(query 或概念名)
输出:1024 维 float 向量(bge-m3),已归一化
两个用法:
  embed_query(text)        → 1 条向量   (StdService 检索时用)
  embed_documents([...])   → 一批向量   (建库工具批量灌库时用,快几十倍)
device:有 GPU 用 cuda,否则 cpu(自动)
```

## 其余细节(次要,一行带过)

【次要】`EmbeddingProvider` 现在只有 HUGGINGFACE 一个枚举值——是**为扩展留的脚手架**(将来加 OpenAI/本地 ONNX 时有位置放),不是写错;`trust_remote_code=True` 是加载 bge-m3 需要的。

## 🧹 死代码 / 盲肠提醒

- 本模块**无死代码**。`EmbeddingProvider` 只有一个枚举值,看着"多余",但它是 factory 里 `if/raise` 分支判断的依据、也是预留扩展点,**别删**。
- 真正可删的相关项不在这里(见第 01 篇的 `abbr_dict`、后面各篇)。

## 🚀 优化方向(更好 / 更稳)

1. **把 device / normalize 提进 config**:现在它们硬编码在 factory 里。提成 `EmbeddingConfig` 字段(如 `device`, `normalize`),配置更集中、测试更好控。
2. **试医学领域 embedding**:bge-m3 是通用模型;临床术语对齐上,`MedCPT`、`SapBERT`、`BioLORD` 这类医学专用嵌入**可能召回更准**(尤其同义词/缩写)。值得做个 A/B:同一批 concept gold,换嵌入看 PASS/canonical 有没有涨。
3. **embedding 缓存**:同一个 expansion 在 benchmark / 反思里会被反复编码;加个 query→vector 的 LRU 缓存能省时间(尤其 CPU 跑时)。
4. **度量一致性做成断言**:建库度量(COSINE)和归一化必须配套。可加一个启动自检:embed 两个已知相似词、断言相似度落在合理区间,防止"换了模型忘了改度量"导致检索悄悄变差。
5. **批大小 / 半精度**:建库时 `embed_documents` 可设 batch_size + fp16(GPU),34.5 万 SNOMED 概念能更快灌完(对应第 04 篇那次 >1 小时的嵌入)。

## 会被追问 / 诚实局限(★主动说)

- **为什么 bge-m3 不是 OpenAI embedding?** 本地可跑、免费、不外发病历数据(合规);通用检索够强。局限是"非医学专用",同义对齐上可能不如医学嵌入——这是第 2 条优化方向。
- **score 的语义**:检索分数来自距离度量,**越大越近还是越小越近要和索引度量对齐**;归一化 + COSINE 下分数越大越相似。这点在 StdService(05)细讲。
- **首次加载慢 / 占内存**:bge-m3 加载要时间、吃内存(并行 benchmark 时每进程各载一份会 OOM,见第 17 篇)。所以它放在 `StdService.__init__` 一次性加载、全程复用。

## 面试怎么说

**合格版(30 秒)**:
> Embedding 层用 config + factory:`EmbeddingConfig` 声明用 bge-m3,`create_embedding_model` 按配置加载,device 自动 cuda/cpu、向量归一化。它把文本编码成向量给 Milvus 检索用。换模型只改 config 一行,调用方不动。

**优秀版(1 分钟)**:
> 我把"用哪个向量模型"和"怎么加载"拆成 config 和 factory 两层:业务代码只依赖 config,换模型或换平台不影响调用方——这套模式我后来又复用到 LLM 上,所以 verify 换模型只改一行。模型选 bge-m3,多语言、长文本、可本地跑不外发病历;开了归一化,配合 Milvus 的 COSINE 度量。device 自动选 GPU/CPU,本机和服务器同一份代码。诚实讲,bge-m3 是通用嵌入,医学同义词对齐上不一定最优,下一步会 A/B 医学专用嵌入;另外建库时几十万概念的编码用 embed_documents 批量做,比逐条快很多。

## 易错点 / 面试问答

**Q:为什么要 factory,不直接 new 一个模型?** A:解耦"选什么"和"怎么用"。换模型/换平台只改 config 或加 factory 分支,调用方零改动;也便于测试时注入假模型。

**Q:normalize_embeddings 为什么要开?** A:归一化后余弦=内积,必须和 Milvus 建库的距离度量(COSINE)对齐,否则相似度分数语义不对。

**Q:bge-m3 维度多少?** A:1024 维;建库时会实测维度来定 collection 的 vector schema(第 03/04 篇)。

**Q:GPU 没有会怎样?** A:自动退 CPU,能跑但慢;所以模型只在 __init__ 加载一次复用,且并行评测要控进程数防 OOM。

## 一句话总结

> Embedding 模块用 config + factory 把"选哪个向量模型"和"怎么加载"解耦:默认 BAAI/bge-m3、归一化、device 自动 cuda/cpu。它负责把文本编码成 1024 维向量,是 RAG 检索(StdService/Milvus)和离线建库的发动机。这套模式后来复用到 LLM 工厂。局限是通用嵌入非医学专用,优化方向是试医学领域嵌入 + 把 device/normalize 提进 config + 加缓存与度量自检。
