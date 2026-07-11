# SNOMED 建库工具（把术语表"灌"进 Milvus，离线一次性）

> 文件：`backend/tools/create_milvus_db.py`（163 行）+ 数据 `backend/data/SNOMED_5000.csv`（5002 条概念）
> 入口：`main()`
> 衔接：上一篇造好了"向量模型"。这篇用它把 SNOMED 医学术语表转成向量、灌进 Milvus，**建出运行时要查的那个库**。建库是离线一次性的；下一篇 StdService 才是运行时拿这个库做检索。

## 核心速记
> 1. **离线建库 vs 在线查询分离**：建库慢（5000 条每条都要 embedding），只跑一次；查询快。这是这个脚本独立存在的根本原因。
> 2. **只对 `concept_name` 做向量**：collection 名就叫 `concepts_only_name`。其他字段（id/code/domain/FSN）只是 metadata，不参与向量检索，查到后取出来用。
> 3. **建库五步**：create → insert → flush → load → search（文件末尾自己总结了）。`COSINE` 度量，和上一篇的归一化对齐。
> 次要（trivia）：`pd.isna` 处理 FSN 空值、`**field` 拆字典、`auto_id=False`——扫一眼。

## 这一段在解决什么

大白话：**把一张 Excel 似的医学术语表，变成一个能"按意思搜"的向量库。**

```text
SNOMED_5000.csv（5000 条标准概念）
   ↓ 每条的 concept_name 用 bge-m3 转成向量
Milvus 向量库 "concepts_only_name"
   ↓ 以后查 "chest pain" 就能找到语义最近的标准概念
```

没有这一步，运行时根本没有库可查。它是整个 RAG 检索的"粮仓"。

## 核心1 · 为什么单独做一个离线脚本（骨架，必背）

建库这件事有两个特点：**慢，而且只需做一次**。

- 5000 条概念，每条都要过一次 bge-m3 算 embedding（CPU 上很慢）；
- 库建好后就固定在那，运行时只读不写。

所以把它**从主服务里拆出来，做成一个独立的离线脚本**，手动跑一次（`python tools/create_milvus_db.py`）。运行时的 StdService 只负责"连上已经建好的库去查"，不重复建。

> 这就是工程里的"**离线索引 / 在线服务分离**"：重活离线做一次，线上只做轻量查询。面试讲 RAG 架构时这是个加分点。

## 核心2 · 只给 concept_name 做向量（这是个设计决定，要会讲）

注意 collection 名字：`concepts_only_name`——**只有"概念名"被向量化**。

schema 一共 7 个字段，但只有一个是向量：

```python
fields = [
    {"field_name":"id",           "datatype":INT64, "is_primary":True},   # 主键=行号
    {"field_name":"concept_id",   "datatype":VARCHAR},   # SNOMED 概念 ID（metadata）
    {"field_name":"concept_name", "datatype":VARCHAR},   # ← 只有它被 embedding
    {"field_name":"domain_id",    "datatype":VARCHAR},   # 领域：Condition/Procedure…
    {"field_name":"concept_code", "datatype":VARCHAR},   # SNOMED 编码
    {"field_name":"vector",       "datatype":FLOAT_VECTOR, "dim":vector_dim},  # ← 向量
    {"field_name":"FSN",          "datatype":VARCHAR},   # 全称 Fully Specified Name
]
```

**翻译这个设计**：检索时靠 `concept_name` 的语义相似度找概念；其余字段（concept_id、code、domain、FSN）是**跟着一起存的"标签"**，查到之后直接取出来用，不参与相似度计算。

```python
vector = embedding_model.embed_query(concept_name)   # 只编码名字
data.append({"id":..., "concept_id":..., "concept_name":..., "vector":vector, "FSN":...})
```

**为什么这么设计**：简单、够用。缺点是只编码了"标准名"一种说法（见诚实局限）。

## 核心3 · 标准建库五步（证明你懂 Milvus 流程）

文件末尾作者自己总结了，背下来：

```text
1. create_collection   建表（schema + 索引）
2. insert              插入 5000 条 {metadata + vector}
3. flush               强制落盘，确保写入完成
4. load_collection     把库加载进内存（不 load 不能搜）
5. search              测试搜 "chest pain" 验证库能用
```

几个关键参数（真实值）：

- **索引**：`index_type="AUTOINDEX"`（让 Milvus 自动选索引类型，省去手动调参）+ `metric_type="COSINE"`（余弦相似度，和上一篇 embedding 归一化对齐）。
- **schema 约束**：`auto_id=False`（主键不让 Milvus 自动生成，用 CSV 行号当 id）+ `enable_dynamic_field=False`（不允许插 schema 之外的字段，结构严格）。
- **向量维度**：脚本不写死，先 `embed_query("test")` 测一下长度再用（bge-m3 实际是 **1024 维**）——这样换模型维度自动适配，是个细心的写法。

## 数据快照：CSV → Milvus 一条记录

```text
CSV 一行（SNOMED_5000.csv，11 列）：
  concept_id=44784427, concept_name="Post diphtheria, tetanus and pertussis vaccination fever",
  domain_id=Condition, concept_code=698578005, FSN="...(disorder)"

  ↓ embed_query(concept_name) → 1024 维向量

Milvus 一条记录：
  { id:0, concept_id:"44784427", concept_name:"Post diphtheria...fever",
    domain_id:"Condition", concept_code:"698578005", FSN:"...", vector:[0.01,-0.03,...] }

测试查询 "chest pain" → 返回 Top-3 语义最近的标准概念
```

## 会被追问 / 诚实局限（★主动说）

- **数据规模小，5000 条**（文件名 `SNOMED_5000` 直说了）。真实 SNOMED CT 有 30+ 万概念。另外 `data/` 里还留着一个 `snomed_sample.csv`（只有 9 行、4 列）——那是更早的玩具版，是进化痕迹。
  → 面试这么说："我用 5000 条 SNOMED 子集验证检索链路跑得通；上真实规模时数据本身不是难点，主要是建库时间（要批量 embedding）和索引调参。"
- **只 embedding 了 `concept_name`，没用 FSN / 同义词**。一个 SNOMED 概念现实里有很多说法（synonyms），只编码标准名会**漏召回**——比如用户写 "MI" 的全称变体，可能匹配不到。
  → "这是当前最大的检索局限。改进方向是把 FSN 和同义词也编码进去（多向量或多条记录），提升召回。"
- **逐行 embedding + 单次构造 insert，没有批量 encode**。5000 条一条条 `embed_query` 很慢。
  → "生产化会用 `embed_documents` 批量编码 + 分批 insert，大幅提速。"
- **`id` 用的是 CSV 行号 `int(idx)`**，重新建库行号会变。稳定标识其实是 `concept_id`。当前 id 只是 Milvus 主键，无业务含义——能讲清这点说明你注意到了。
- **Milvus URI 写死 `127.0.0.1:19530`**，AUTOINDEX 也没手动调参。小数据无所谓，大规模要手动选 HNSW/IVF 并调 `nlist/ef` 等。
- **没有去重 / concept_name 清洗**：CSV 里可能有重复或脏名字，直接全量入库。

## 面试怎么说

**合格版（30 秒）**：
> 向量库是离线建的：读 5000 条 SNOMED CSV，对每条的 concept_name 用 bge-m3 算向量，灌进 Milvus 的 `concepts_only_name` collection，索引用 AUTOINDEX + COSINE。流程是 create→insert→flush→load→search。建库一次性，运行时只读。

**优秀版（1 分钟）**：
> 我把建库做成独立离线脚本，因为它慢且只需一次——5000 条每条都要 embedding。schema 里只有 concept_name 被向量化，concept_id、code、domain、FSN 都是跟着存的 metadata，检索靠概念名的语义相似度，命中后取 metadata 用。度量用 COSINE，和 embedding 侧的归一化配套。向量维度我不写死，先测一条再建，换模型自动适配。诚实说两个局限：一是只编码了标准名、没用同义词，会漏召回，这是改进重点；二是逐行 embedding 没批量，规模上去要优化。数据也只是 5000 条子集，用来验证链路，不是全量 SNOMED。

## 易错点 / 面试问答

**Q：为什么建库要单独一个脚本，不放服务里？** A：建库慢且只需一次（离线索引），线上只做查询（在线服务）。两者分离是标准做法。

**Q：为什么只对 concept_name 做向量？** A：MVP 取舍，靠概念名语义匹配就够验证链路。局限是漏同义词召回，改进是把 FSN/synonyms 也编码。

**Q：flush 和 load 分别干嘛？** A：flush 把 insert 的数据强制落盘确保写完；load 把 collection 加载进内存——不 load 不能搜。

**Q：AUTOINDEX 是什么？** A：让 Milvus 自动选索引类型，省手动调参。小数据够用，大规模建议手动选 HNSW/IVF 并调参。

**Q：5000 条够用吗？** A：够验证架构。真实 SNOMED 30+ 万，全量上库主要挑战是建库耗时和索引调参，检索逻辑不变。

## 一句话总结

> `create_milvus_db.py` 是离线一次性脚本：读 5000 条 SNOMED CSV，只对 `concept_name` 用 bge-m3 算向量，按 create→insert→flush→load→search 五步灌进 Milvus 的 `concepts_only_name`，索引 AUTOINDEX + COSINE（与归一化对齐）。其余字段作为 metadata 随存随取。它是 RAG 检索的"粮仓"。局限是规模小（5000 子集）、只编码标准名漏同义词、逐行无批量——都是"验证链路用、生产可优化"的取舍。
