# StdService —— Embedding + Milvus 多源检索底座 · V11 🔄

> 文件:`backend/services/std_service.py`(58 行,薄但关键)
> 衔接:**它是 RAG 检索的最底层执行器**——把一句 query 编码成向量,丢进 Milvus 的**某个库**搜回最近的概念。上面是 MedicalRetriever(第 06 篇,加规则重排);它下面是 bge-m3(第 02 篇)和建库工具灌好的 Milvus(第 04 篇)。
> **V11 变化(必看)**:从"只连一个库"升级成"**多源**"——一个 `collections` 字典管 SNOMED 和 RxNorm 两个 collection,`search_similar_terms` 多了个 `source` 参数,这是 L3 多源路由能落地的物理底座。

## 核心速记
> 1. **多源 = 一个字典 + 一个 source 参数**:`collections = {"snomed": concepts_only_name, "rxnorm": rxnorm_concepts}`;`search_similar_terms(query, limit, source="snomed")` 按 source 选库搜。必背:**它只负责"按你点的库去搜",决定点哪个库是上层的事(路由)**。
> 2. **懒加载 collection**:`__init__` 只 load 默认源(snomed);别的源**第一次被搜到时**才 `load_collection`(`_ensure_loaded` + `_loaded` 集合去重)。省内存、加速启动。
> 3. **干一件事**:`query →embed_query→ 向量 → client.search(该库) → 概念列表(带 score)`。score = `round(distance,4)`。
> 次要(trivia):`MILVUS_URI` 默认 `127.0.0.1:19530`;output_fields 固定那 5 个;FSN 是建库时用 concept_name 顶替的。

## 这一段在解决什么

大白话:**"给我一句话,我去指定的医学库里找最像的几个标准概念。"**

```text
search_similar_terms("chest pain", limit=10, source="snomed")
   → 在 SNOMED 库搜 → [{concept_name:"Chest pain", score:0.99}, ...]

search_similar_terms("aspirin", limit=10, source="rxnorm")
   → 在 RxNorm 库搜 → [{concept_name:"aspirin", concept_code:"1191", score:1.0}, ...]
```

它不重排、不过滤、不判断忠实度——那些是上层(retriever / verify)的事。它只做"编码 + 向量搜索"这一步。

## 核心1 · 多源:一个字典把"病库/药库"统一管起来(V11 关键)

```python
def __init__(self):
    self.collections = {
        "snomed": os.getenv("MILVUS_COLLECTION_NAME", "concepts_only_name"),
        "rxnorm": os.getenv("MILVUS_RXNORM_COLLECTION", "rxnorm_concepts"),
    }
    self.default_source = "snomed"
    self.embedding_model = create_embedding_model(EmbeddingConfig())   # bge-m3
    self.client = MilvusClient(uri=self.milvus_uri)
    self._ensure_loaded(self.collections[self.default_source])         # 先 load 默认源

def search_similar_terms(self, query, limit=5, source="snomed"):
    collection = self.collections.get(source, self.collections[self.default_source])  # 未知源回退默认
    self._ensure_loaded(collection)                 # 该源没 load 过就 load 一次
    query_vector = self.embedding_model.embed_query(query)
    search_result = self.client.search(collection_name=collection, data=[query_vector],
                                       anns_field="vector", limit=limit,
                                       output_fields=["concept_id","concept_name","domain_id","concept_code","FSN"])
    # → 拼成 [{input, concept_id, concept_name, domain_id, concept_code, FSN, score=round(distance,4)}]
```

要点:
- **加 source 之前**:整个项目只有一个库,所有词都查 SNOMED;
- **加 source 之后**:同一个 StdService 能查任意源,只看你传 `source="snomed"` 还是 `"rxnorm"`。**默认 snomed → 向后兼容**(老调用不传 source 时行为不变,这是 L3 Stage-2 能"行为中性"上线的原因)。
- **未知 source 自动回退默认**:传错也不崩,退回 snomed。
- **决定查哪个库不在这里**:StdService 只执行;"病走 snomed、药走 rxnorm"的路由判断在 ABBRService 的 `_route_source`(第 15 篇),一路 source 透传下来。

## 核心2 · 懒加载 collection:省内存、稳启动

```python
self._loaded = set()
def _ensure_loaded(self, collection_name):
    if collection_name not in self._loaded:
        self.client.load_collection(collection_name=collection_name)  # Milvus 把该库装进内存才可搜
        self._loaded.add(collection_name)
```

- Milvus 的 collection 要 `load` 进内存才能搜;几十万条向量 load 是有内存代价的。
- 所以:**启动只 load 默认的 snomed**;rxnorm **等真有药品 query 来了**才 load。一个 `_loaded` 集合记录已加载、避免重复 load。
- 好处:没有药品输入的场景不白占 RxNorm 的内存;启动更快。

## 数据快照

```text
输入:query(str), limit(int, 默认5,实际上层传10), source("snomed"/"rxnorm")
输出:list[dict],每条 = { input, concept_id, concept_name, domain_id, concept_code, FSN, score }
score:round(distance,4);COSINE + 归一化下,越大越相似(0~1)
两个库:concepts_only_name(SNOMED 34.5万) / rxnorm_concepts(RxNorm 15.7万)
连接:MILVUS_URI(默认 http://127.0.0.1:19530)
被谁调:MedicalRetriever(它持有一个 StdService 实例)
```

## 其余细节(次要,一行带过)

【次要】`output_fields` 固定取 5 个标量字段(向量本身不取回);`FSN` 取回但和 concept_name 相同(建库顶替);`limit` 默认 5 但 retriever 总传 top_k=10。

## 🧹 死代码 / 盲肠提醒

- 本文件**无死代码**,很干净。`default_source` / 未知源回退 / `_loaded` 都在用。
- 半个"数据盲肠":**`FSN` 字段一路取回但其实等于 concept_name**(建库时顶替的,见第 04 篇)。不影响功能(检索用 concept_name),但如果你后期不打算填真 FSN,可考虑建库时干脆不存它、检索也不取,省一点存储/带宽。属可选清理,非必须。

## 🚀 优化方向(更好 / 更稳)

1. **score/distance 命名澄清**:pymilvus 返回的 `item["distance"]` 在 COSINE 下其实是"相似度(越大越近)",代码把它命名成 `score` 没问题,但建议加注释/常量写明度量,避免后人误以为"距离越小越近"调反阈值。
2. **把 domain 过滤下推 Milvus(可选)**:现在领域是上层做**软加分**(retriever),没在向量搜索阶段过滤。若将来要硬过滤某域,可用 Milvus 的 `filter=` 表达式在搜索层做,省得捞回再筛。**注意**:项目刻意选"软加分"而非"硬过滤"(不弄丢答案),所以这条是"按需",不是缺陷。
3. **预热两个库(可选)**:若线上药品输入很常见,可启动时把 rxnorm 也 load,首个药品请求不卡在冷加载。
4. **取回更多字段**:建库存了 concept_class_id/同义词后,output_fields 带上,给重排/过滤更多信号(联动第 04、06 篇)。
5. **健康检查 + 容错**:Milvus 不可用 / collection 不存在时给清晰报错(现在会直接抛 pymilvus 异常);可包一层友好提示 + 让 `/health` 真探一下 Milvus(现在 /health 不查 Milvus,见第 16 篇)。
6. **连接复用/池化**:并行评测时每个 service 各建一个 MilvusClient;量大可考虑连接池。

## 会被追问 / 诚实局限(★主动说)

- **多源怎么实现的?** 一个 collections 字典 + search 的 source 参数 + 懒加载;默认 snomed 向后兼容。决定查哪个库的路由在上层(_route_source)。
- **score 是什么?** Milvus 在 COSINE 度量下返回的相似度,round 到 4 位;归一化后越大越相似。
- **为什么不在这层做领域过滤?** 项目选"软加分不硬过滤",避免映射不准时把正确答案弄丢;所以过滤/加分放在 retriever 的重排里。
- **FSN 没真值**:这版用 concept_name 顶替,不影响检索;要严谨可补。
- **冷启动**:首次搜某个库要 load,会慢一下;之后复用。

## 面试怎么说

**合格版(30 秒)**:
> StdService 是检索底座:用 bge-m3 把 query 编码,丢进 Milvus 搜回最近的概念。V11 做成多源——一个 collections 字典管 SNOMED 和 RxNorm 两个库,search 带 source 参数选库,默认 snomed 向后兼容,collection 懒加载。它只负责编码+搜索,重排和判断在上层。

**优秀版(1 分钟)**:
> 这层把"文本→向量→Milvus 搜索"封装成 search_similar_terms。V11 的关键改造是多源:原来只连一个库,我改成 collections 字典 + source 参数,同一个 StdService 能查 SNOMED 或 RxNorm,默认 snomed 所以老调用零影响——这就是 L3 路由能行为中性上线的底座。collection 是懒加载的,启动只 load 默认源、药品库等第一个药品 query 来才 load,省内存。它职责很窄:只编码和搜索,score 是 COSINE 相似度;领域加分和忠实度判断我刻意放在上层(retriever 软加分、verify 判忠实),不在这层硬过滤,避免弄丢正确答案。

## 易错点 / 面试问答

**Q:多源是怎么切的?** A:search 的 source 参数 → collections 字典查出 collection 名 → 在那个库搜。路由判断在上层 _route_source,这里只执行。

**Q:懒加载是懒什么?** A:懒 load Milvus collection 进内存。启动只 load snomed,rxnorm 首次被搜才 load,用 _loaded 集合去重。

**Q:score 越大越近还是越小?** A:COSINE+归一化下越大越相似;它是 Milvus 返回的 distance 字段 round 后改名 score。

**Q:为什么不在这层按 domain 过滤?** A:项目选软加分(retriever 里 +0.2)而非硬过滤,防止映射不准把正确概念过滤掉。

**Q:传了不存在的 source 会怎样?** A:回退默认 snomed,不崩。

## 一句话总结

> StdService 是 RAG 的执行底座:bge-m3 编码 query + Milvus 向量搜索,返回带 score 的概念列表。V11 把它升级成多源——collections 字典 + source 参数让同一个服务能查 SNOMED/RxNorm,默认 snomed 向后兼容、collection 懒加载,是 L3 多源路由的物理底座。它职责很窄(只编码+搜索),重排和忠实度判断都在上层。无死代码;优化方向是 score 度量澄清、按需下推过滤、预热与多字段、容错与连接复用。
