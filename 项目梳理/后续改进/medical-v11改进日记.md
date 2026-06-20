在原先v9的基础上我发现了很多问题，并且让claude整理问题生成v11的改进方案。在6月20号开始着手改动以下是改动日记。

1. 在初始时，我先用git保证了原始的项目进度"save current medical project state before refactor"，并且为改动设定了专门的分支tag medical-before-refactor

2. 批次1

3. 批次2

4. 批次3出问题。因为改动的两个方向是相反的改动。1.fallback产出topk=3它让 LLM 给"本不该扩"的缩写**造出更多像模像样的假扩写**。**NER `is_medical` 杀烂候选** = 太弱。NER 只能识别"像不像医学实体",但 LLM 造的假扩写("Nocturnal Oxygen Protocol")**本来就长得像医学**,NER 根本拦不住------>**改动**(coverage 之后对 fallback 缩写加弃权门。故事点：**"low_context 过度扩写,我第一反应是给 fallback 多产候选 + 用本地 NER 过滤垃圾。结果 net 掉了——top-k 反而让 LLM 给非临床 token 造出更多'像医学'的假扩写,NER 还拦不住同源幻觉。我用 benchmark 量到净收益为负,立刻回退,然后重新诊断:low_context 的病根是'该弃权不弃权',方向应该是让系统更倾向不扩,而不是产更多候选。于是改成对证据不足的 fallback 缩写直接弃权。这正是项目的核心纪律:加东西看的是对整体指标的净影响,不是它解决的单点。"**

5. 之后对fallback进行质疑觉得基本不需要他因为原始的benchmark测评集是ai手写的基本候选集路1就可以走的正确率很高，如果一味的追求benchmark的正确率只能让优化变得没有适配性，很单一。所以还是要保留fallback防止让AI在进行优化是因为一个案例将普通性给直接砍掉这样很极端。

6. 增加专业的医疗数据进入benchmark,让项目鲁棒性更强而不是只针对一个方向优化。

7. 在加入多个case进入benchmark之后发现经常运行一半就会中断。这是网络/TLS 瞬断解决方法：**单个 case 的网络瞬断会自动重试 3 次(间隔 3 秒);实在不行就把那一个 case标记为失败、继续跑完**

8. 假阴性。发现问题对于新增的case。在fallback中确实扩写对了但是只是将其扩写首字母写成大写但是案例最后标准答案是小写。或者fallback扩写的医疗名称和标准答案的医疗名称都指向同一种病如["primary care physician", "primary care provider"]只是最后的单词不一样。这个就是llm会飘。解决方法:**SNOMED concept_id 比对——最贴合项目主旨、最严谨。 这本就是个"SNOMED 标准化"项目:不比字符串,比两个扩写映射到的 SNOMED 概念是否同一个 concept_id。"physician/provider" 很可能落到同一个 SNOMED 概念 → 判对**
   。**改动 1 = 改"答案本"**(数据):你在标准答案里写上"PCP 这题,physician 和 provider 都算对"。

   **改动 2 = 改"阅卷规则"**(代码):`compare_mappings_snomed` 这个函数,是拿**系统的那一个答案**去跟标准答案对、判对错的。LLM 还是只生成**一个**答案,改动 2 只是改"怎么判这一个答案对不对"。

9. 项目在运行benchmark时速度太慢了。原因：benchmark 74 例**串行**,而每一例内部又是一串**阻塞式的 DeepSeek API 调用**:coverage(每个缩写一次)、fallback(每个非词典缩写一次)、verify(每轮一次)、可能还有 reflect 重试。算下来一轮是**几百次顺序网络往返**,每次等 1~几秒。本地的 NER、embedding、Milvus 检索其实很快——**瓶颈 95% 是在网络上干等 DeepSeek 回包**。解决方法：**并行运行每线程独立 service(上面 `threading.local` 那样,推荐):每个工作线程各自加载一份模型,互不干扰。代价是 N 份模型内存——bge-m3 ~2GB,4 个 worker ≈ 8GB+。内存够就用这个,正确性最稳。**

10. 之后先做批次5因为他的改动影响比较明显