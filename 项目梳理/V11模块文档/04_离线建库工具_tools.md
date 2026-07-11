# 离线建库工具(把官方词表灌成项目能搜的向量库)· V11 🔄

> 文件:`backend/tools/` 下四个脚本(SNOMED 一对、RxNorm 一对):
> - `build_concept_csv.py` + `rebuild_milvus.py`(SNOMED → collection `concepts_only_name`)
> - `build_rxnorm_csv.py` + `rebuild_rxnorm_milvus.py`(RxNorm → collection `rxnorm_concepts`)
> 衔接:这是**离线一次性**工作,不在请求里跑。它把官方医学词表变成 Milvus 里的向量库;之后 StdService(第 05 篇)才有东西可搜。**V11 两大变化**:① SNOMED 从 5000 样例升级到**全量临床标准概念**;② 新增**第二个库 RxNorm**(L3 多源的物理底座)。

## 核心速记
> 1. **两步法**:先 `build_*_csv` 从官方大词表(OHDSI Athena 的 CONCEPT.csv,130 万+ 行、Tab 分隔)**按列筛行**成项目用的小 CSV;再 `rebuild_*_milvus` 把概念名**批量编码**灌进 Milvus。筛 + 灌分开。
> 2. **两个库各管一摊**:`concepts_only_name`(SNOMED,疾病/症状/操作/检验,约 34.5 万)+ `rxnorm_concepts`(RxNorm 药品,15.7 万,其中 Ingredient 1.46 万)。RxNorm 脚本**绝不碰** SNOMED 库(只新增,互不干扰)。
> 3. **批量编码是提速关键**:`embed_documents(一批256)` 比老脚本逐条快几十倍;AUTOINDEX + COSINE 度量(和第 02 篇的归一化对齐)。
> 次要(trivia):筛出的 CSV 只留 5 列(concept_id/concept_name/domain_id/concept_code/FSN),FSN 这版用 concept_name 顶替;CSV 已 gitignore(产物不进库)。

## 这一段在解决什么

大白话:**官方医学词表有上百万条、还是一坨制表符大文件,机器搜不动也用不上。这组工具把它"筛瘦 + 编码"成项目能向量检索的库。**

```text
Athena CONCEPT.csv(130万+,OMOP 格式,Tab 分隔)
   │  build_concept_csv.py:按列筛(只要 SNOMED + 标准 + 有效 + 临床域)
   ▼
backend/data/snomed_clinical.csv(约 34.5 万条,5 列)
   │  rebuild_milvus.py:bge-m3 批量编码 + 灌 Milvus
   ▼
Milvus collection: concepts_only_name(可向量检索)
```

RxNorm 走另一对脚本,出 `rxnorm_concepts`。**chest pain 最终落在 SNOMED 库、aspirin 落在 RxNorm 库**——这就是后面"病/药分库检索"的底座。

## 核心1 · 第一步 build_*_csv:从百万词表"按列筛行"(不用懂医学)

筛选就是几条机器判断(以 SNOMED 为例):

```python
m = (df["vocabulary_id"] == "SNOMED")        # 只要 SNOMED,不要 ICD/RxNorm
  & (df["standard_concept"] == "S")          # 只要"标准概念"(规范节点)
  & (df["invalid_reason"].fillna("") == "")  # 只要还有效的
  & (df["domain_id"].isin(CLINICAL_DOMAINS)) # 只要临床域(Condition/Procedure/Measurement/...)
```

RxNorm 那条只换两处:`vocabulary_id=="RxNorm"` 且 `domain_id=="Drug"`(并打印 concept_class 分布,确认 Ingredient 成分级概念在内)。

**为什么要先筛**:130 万条里大半是别的词表/废弃/非临床节点,全灌进去既慢又会拉低检索精度。筛成几十万条"干净的标准临床/药品概念",检索才准。

**★一个踩过的坑(面试可讲)**:`MAX_ROWS` 一度设成 12 万 + `df.head(12万)`——按行序硬截,把"高血压/冠心病"这种**通用母概念**随机切没了,导致标准化大量弃码。**改成 `MAX_ROWS=None`(全量)后才修好**。教训:别用"取前 N 行"当采样,会丢关键长尾。

## 核心2 · 第二步 rebuild_*_milvus:批量编码 + 重建库

```text
读筛好的 CSV → 加载 bge-m3 → 实测向量维度(1024)
→ 连 Milvus → drop 旧 collection → 建 schema(含 vector 字段)
→ 建索引(AUTOINDEX, metric=COSINE)
→ 按 256 一批:embed_documents(names) → insert
→ flush + load → 自测一条(SNOMED 测 'chest pain' / RxNorm 测 'aspirin')
```

要点:
- **批量编码**:`embed_documents` 一次算一批(256),比老的逐条 `embed_query` 快几十倍(15.7 万 RxNorm 仍要 >1 小时,可见规模)。
- **schema 七字段**:id / concept_id / concept_name / domain_id / concept_code / vector(dim) / FSN。检索回来的 metadata 就来自这里(第 05 篇)。
- **COSINE + 归一化配套**:索引度量 COSINE,必须和第 02 篇的 `normalize_embeddings=True` 对齐,分数语义才对。
- **代码侧零改**:重建用的还是 `concepts_only_name` 同名同结构,所以换全量库时**业务代码一行没动**——这验证了之前"瓶颈是数据不是代码"的诊断。
- **RxNorm 安全隔离**:`rebuild_rxnorm_milvus` 只建 `rxnorm_concepts`,不 drop SNOMED 库。

## 数据快照

```text
源:OHDSI Athena CONCEPT.csv(OMOP 标准格式,Tab 分隔,~130万行/约50列)
   注:SNOMED 和 RxNorm 来自【两个不同的 Athena 下载包】(路径不同,见脚本顶部 INPUT_CSV)
SNOMED:筛后 ~345,882 条 → concepts_only_name
RxNorm:RxNorm 行 315,157 → 标准+有效+Drug 157,190(Ingredient 14,610)→ rxnorm_concepts
落地:5 列 CSV(gitignore)→ Milvus 7 字段 collection(AUTOINDEX/COSINE)
自测:chest pain→'Chest pain'/0.99;aspirin→'aspirin'/1.0(code 1191)
```

## 其余细节(次要,一行带过)

【次要】FSN(全限定名)这版直接用 concept_name 顶替(Athena 这个导出里没单独 FSN 列);`INPUT_CSV` 是写死的本机绝对路径(两份不同 Athena 包);`rxnorm_clinical.csv`/`snomed_clinical.csv` 都 gitignore。

## 🧹 死代码 / 盲肠提醒

- **`tools/create_milvus_db.py` = 老的逐条建库脚本,已被 `rebuild_milvus.py`(批量)取代**。它读的是老的 `snomed_sample.csv`(5000 样本),全项目**无任何代码引用**(只在注释里被提到)。
  → **可归档/删除**(确认你不再手动跑它)。它代表的是"5000 稀疏样本"那个旧时代。
- **过时指引**:`build_concept_csv.py` 结尾打印"下一步:把 **create_milvus_db.py** 的 CSV_PATH 指到这个文件"——这句**已过时**,现在应指向 `rebuild_milvus.py`。建议改这句注释,免得后期照着老脚本走。
- `tools/show_snomed_file.py` 是看文件用的小调试脚本,留着无害;不确定还用不用可归档。

## 🚀 优化方向(更好 / 更稳)

1. **路径别写死**:`INPUT_CSV` 改成命令行参数或环境变量,换下载包不用改代码。
2. **合并重复脚本**:两个 build(只差 vocabulary_id/domain)、两个 rebuild(几乎一模一样)可各合成一个、用参数区分 source。现在是复制粘贴,改一处要改两份。
3. **建库提速**:batch 可调大 + GPU/半精度(fp16);15.7 万要 >1 小时,全量 SNOMED 更久。也可多进程并行编码。
4. **重建更安全**:`drop + 重建`是破坏性的。可加"先建临时 collection→灌完校验条数→再原子切换别名"的蓝绿做法,避免重建中途失败把库搞空。
5. **增量更新**:词表年度更新时,做"只插新增/失效下线",而不是每次全量重灌。
6. **存更多字段**:把 `concept_class_id`、同义词(CONCEPT_SYNONYM)也灌进去,检索/重排能用上更多信号(比如同义词召回、按 class 过滤),也能给 FSN 填真值而非顶替。
7. **建库自检入 CI 口径**:每次重建后自动跑几条已知 query 断言 top1(chest pain→Chest pain、aspirin→aspirin),库坏了立刻发现。

## 会被追问 / 诚实局限(★主动说)

- **数据哪来的、规模?** OHDSI Athena 官方词表(SNOMED + RxNorm),OMOP 标准格式;筛成 SNOMED ~34.5 万、RxNorm 15.7 万。
- **为什么先筛再灌?** 130 万里大半非临床/废弃,全灌慢且拉低精度;筛成干净标准概念检索才准。
- **MAX_ROWS 那个坑**:用 head(N) 截断会丢通用母概念→大量弃码,改全量修好。这是"采样别用取前 N 行"的教训。
- **建库慢**:几十万条 bge-m3 编码要很久(RxNorm >1 小时),所以是**离线一次性**,不在请求路径。
- **FSN 是顶替的**:这版没真 FSN;不影响检索(检索用 concept_name),但要严谨可补真值。

## 面试怎么说

**合格版(30 秒)**:
> 建库是离线两步:先从 Athena 的 CONCEPT.csv(130 万+)按 vocabulary/standard/domain 筛成几十万条干净 CSV,再用 bge-m3 批量编码灌进 Milvus。SNOMED 进 concepts_only_name、RxNorm 进 rxnorm_concepts,两个库各管疾病和药品。索引 AUTOINDEX + COSINE。

**优秀版(1 分钟)**:
> 知识库是离线建的:build 脚本从 OHDSI Athena 的百万级词表里按列筛出标准、有效、临床域的概念;rebuild 脚本用 bge-m3 批量编码(256 一批,比逐条快几十倍)灌进 Milvus,AUTOINDEX + COSINE,和 embedding 的归一化对齐。V11 这里有两件大事:SNOMED 从早期 5000 样本升级到全量 34.5 万——而且代码一行没改,只换了库,直接验证了我之前'瓶颈是数据不是代码'的诊断;以及新增 RxNorm 第二个库做多源,RxNorm 脚本刻意不碰 SNOMED 库。我还踩过一个坑:早期用 head(12万) 截断,把通用母概念切没了导致弃码,改全量修复——这让我对'采样不能取前 N 行'印象很深。

## 易错点 / 面试问答

**Q:为什么分两步(筛 CSV 和灌库)?** A:解耦。筛是数据清洗(pandas),灌是编码+索引(Milvus);分开便于检查中间产物、重灌不必重筛。

**Q:两个库会互相影响吗?** A:不会。RxNorm 脚本只建 rxnorm_concepts,不 drop SNOMED;StdService 靠 source 参数选库(第 05 篇)。

**Q:COSINE 和归一化什么关系?** A:必须配套。embedding 归一化后,COSINE 等价内积,分数语义才正确;换度量不换归一化会悄悄错。

**Q:建库要多久?** A:几十万条 bge-m3 编码很慢(RxNorm >1 小时),所以离线一次性做、请求里不跑。

**Q:create_milvus_db.py 还用吗?** A:不用了,它是逐条的老版(读 5000 样本),已被批量的 rebuild_milvus 取代,可归档。

## 一句话总结

> 这组离线工具把 OHDSI Athena 的百万级官方词表,两步变成项目能向量检索的库:build_*_csv 按列筛出标准临床/药品概念,rebuild_*_milvus 用 bge-m3 批量编码灌进 Milvus(AUTOINDEX/COSINE)。产出 SNOMED 的 concepts_only_name(34.5万)和 RxNorm 的 rxnorm_concepts(15.7万),是多源检索的底座。V11 把 SNOMED 升到全量(代码零改,验证瓶颈在数据)并加了 RxNorm 第二库。盲肠是逐条老脚本 create_milvus_db.py;优化方向是参数化路径、合并重复脚本、蓝绿重建与增量更新。
