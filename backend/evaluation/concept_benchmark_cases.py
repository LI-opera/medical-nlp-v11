"""
Concept 层 benchmark gold(标准化层评测)
================================================================
动机:
  现有 benchmark 只判 (缩写, 扩写),【测不到】verify 自批次8 起的全部标准化工作
  (在检索候选里选忠实 SNOMED 概念 / 弃码)。本文件补上 concept 层的尺子:
  给定【正确扩写】,标准化这一步该选哪个概念、还是该弃码。

口径(诚实):
  - 用【概念名】判等,不用 concept_id(gold 的 id 取决于具体 Athena 下载;概念名稳定可读)。
    runner 会打印实际选中的名字,库里 FSN 略有出入就照实际名补进 accept。
  - prefer = 最规范的概念;accept = 其它也忠实可接受的写法。
    PASS = 选中在 {prefer}+accept 里;canonical = 选中 == prefer。
    PASS 看忠实度,canonical 看规范度;两者差 = reflection/改写能改善的余量
    (实测:SOB 'Difficulty breathing' -> 'Dyspnea')。
  - confirmed=True = 已用探针/诊断/首跑核过的硬 gold(计入准确率)。

测什么:给定正确扩写,标准化选概念的忠实度+规范度+该弃码时弃码。
不测:扩写消歧(那是现有 benchmark + coverage 的活)。两层合起来覆盖项目两块。
"""

CONCEPT_BENCHMARK_CASES = [
    {
        "label": "CP", "expansion": "chest pain", "expect": "concept",
        "prefer": "Chest pain", "accept": [], "confirmed": True,
        "note": "top0 0.99",
    },
    {
        "label": "DM", "expansion": "diabetes mellitus", "expect": "concept",
        "prefer": "Diabetes mellitus", "accept": [], "confirmed": True,
        "note": "top0 0.935",
    },
    {
        "label": "MI", "expansion": "myocardial infarction", "expect": "concept",
        "prefer": "Myocardial infarction", "accept": [], "confirmed": True,
        "note": "top0 0.957",
    },
    {
        "label": "PNA", "expansion": "pneumonia", "expect": "concept",
        "prefer": "Pneumonia", "accept": [], "confirmed": True,
        "note": "top0 0.785",
    },
    {
        "label": "CHF", "expansion": "congestive heart failure", "expect": "concept",
        "prefer": "Congestive heart failure", "accept": [], "confirmed": True,
        "note": "top0 0.924",
    },
    {
        "label": "HTN", "expansion": "hypertension", "expect": "concept",
        "prefer": "Hypertensive disorder", "accept": ["Essential hypertension"], "confirmed": True,
        "note": "通用概念排第9,靠 top-3->top-10 窗口才够到",
    },
    {
        "label": "SOB", "expansion": "shortness of breath", "expect": "concept",
        "prefer": "Dyspnea", "accept": ["Difficulty breathing"], "confirmed": True,
        "note": "主链路只够到 'Difficulty breathing'(accept);'Dyspnea' 要改写才捞到=batch9 目标",
    },
    {
        "label": "CAD", "expansion": "coronary artery disease", "expect": "concept",
        "prefer": "Coronary arteriosclerosis",
        "accept": ["Disorder of coronary artery", "Ischemic heart disease"], "confirmed": True,
        "note": "边界:top-10 下 verify 弃码;规范概念要改写才捞到",
    },
    {
        "label": "ASTHMA", "expansion": "asthma", "expect": "concept",
        "prefer": "Asthma", "accept": [], "confirmed": True,
        "note": "首跑确认 canonical",
    },
    {
        "label": "AFIB", "expansion": "atrial fibrillation", "expect": "concept",
        "prefer": "Atrial fibrillation", "accept": [], "confirmed": True,
        "note": "首跑确认 canonical",
    },
    {
        "label": "RA_room_air", "expansion": "room air", "expect": "concept",
        "prefer": "Breathing room air", "accept": [], "confirmed": True,
        "note": "首跑 verify 选 'Breathing room air'(忠实),原弃码假设错;本集暂无真负例待补",
    },
    {
        "label": "ASA", "expansion": "aspirin", "expect": "concept",
        "domain": "Drug",
        "prefer": "aspirin", "accept": [], "confirmed": True,
        "note": "Drug→RxNorm;首跑确认 ingredient 概念名",
    },
    {
        "label": "MTX", "expansion": "methotrexate", "expect": "concept",
        "domain": "Drug",
        "prefer": "methotrexate", "accept": [], "confirmed": True,
        "note": "Drug→RxNorm;首跑确认",
    },
    {
        "label": "APAP", "expansion": "acetaminophen", "expect": "concept",
        "domain": "Drug",
        "prefer": "acetaminophen", "accept": [], "confirmed": True,
        "note": "Drug→RxNorm;首跑确认(美式 RxNorm 用 acetaminophen)",
    },
    {
        "label": "HCTZ", "expansion": "hydrochlorothiazide", "expect": "concept",
        "domain": "Drug",
        "prefer": "hydrochlorothiazide", "accept": [], "confirmed": True,
        "note": "Drug→RxNorm;首跑确认",
    },
    {
        "label": "NTG", "expansion": "nitroglycerin", "expect": "concept",
        "domain": "Drug",
        "prefer": "nitroglycerin", "accept": [], "confirmed": True,
        "note": "Drug→RxNorm;首跑确认",
    },
]
