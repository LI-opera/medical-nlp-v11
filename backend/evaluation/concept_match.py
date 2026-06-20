"""
SNOMED concept_id 语义等价判等(评测口径升级 ②)
================================================================

动机:
  旧 compare_mappings 卡 (缩写, 扩写) 字符串完全相等,会把
  "primary care provider" 判成 ≠ "primary care physician"——语义对、字面不同。
  本项目本就是"SNOMED 术语标准化",更该用【两个扩写映射到的 SNOMED 概念是否同一】
  来判等价,而不是比字符串。

设计(混合,诚实面对稀疏库):
  - SNOMED_5000.csv 只是 5000 条样本,很多扩写(room air / heart rate /
    mitral stenosis ...)根本不在库里 → 解析不出 concept。
  - 故采用混合判等:
      1) 归一化字符串相等 → 等价(快路径,且覆盖库里没有的扩写)
      2) 两个扩写都能【可靠解析】到 SNOMED 概念(score≥阈值)且 concept_id 相同 → 等价
      3) 否则不等价
  - 确定性:bge-m3 embedding + Milvus 检索是确定的,不引入 LLM 噪声。

覆盖局限(诚实记一笔):
  concept_id 判等只在【两个扩写都落进 5000 样本库且检索可靠】时生效;
  库外扩写退回字符串判等。要全覆盖需更大的 SNOMED 库。
"""


def normalize_text(text):
    if text is None:
        return None
    return text.strip().lower()


# 扩写 -> top concept_id 的解析缓存(同一扩写只检索一次,省 Milvus 调用)
_concept_cache = {}


def top_concept_id(service, expansion, score_threshold=0.6):
    """把一个扩写解析成 SNOMED top-1 concept_id;库里无可靠匹配则返回 None。"""
    if not expansion:
        return None
    key = normalize_text(expansion)
    if key in _concept_cache:
        return _concept_cache[key]
    concept_id = None
    try:
        docs = service.retriever.retrieve(
            query=expansion,
            top_k=5,
            domain_filter=None,
            score_threshold=score_threshold,
        )
        if docs:
            concept_id = docs[0]["metadata"].get("concept_id")
    except Exception:
        concept_id = None
    _concept_cache[key] = concept_id
    return concept_id


def expansions_equivalent(service, exp_pred, exp_gold, score_threshold=0.6):
    """判两个扩写是否语义等价:字符串相等 OR 同一 SNOMED concept_id。"""
    a, b = normalize_text(exp_pred), normalize_text(exp_gold)
    if a is None or b is None:
        return False
    if a == b:
        return True
    cid_pred = top_concept_id(service, exp_pred, score_threshold)
    cid_gold = top_concept_id(service, exp_gold, score_threshold)
    return cid_pred is not None and cid_pred == cid_gold


def compare_mappings_snomed(service, expected_mappings, predicted_mappings, score_threshold=0.6):
    """评测判对:
    - 缩写集合必须完全一致(仍严判多扩/少扩 → 保住 QRS/NOP 过度扩写的检测、abstain 的检测)
    - 每个缩写的扩写按【语义等价】判(字符串 OR SNOMED concept_id)
    """
    pred = {}
    for m in predicted_mappings:
        abbr = normalize_text(m.get("abbreviation"))
        exp = m.get("expansion")
        if abbr and exp:
            pred[abbr] = exp

    gold = {}
    for m in expected_mappings:
        abbr = normalize_text(m.get("abbreviation"))
        exp = m.get("expansion")
        if abbr and exp:
            gold[abbr] = exp

    # 缩写集合必须一致(多扩/少扩/该弃权没弃 → 直接判错)
    if set(pred.keys()) != set(gold.keys()):
        return False

    # 逐缩写判扩写语义等价
    for abbr in gold:
        if not expansions_equivalent(service, pred[abbr], gold[abbr], score_threshold):
            return False
    return True
