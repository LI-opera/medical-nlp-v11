"""
医学缩写候选库（Medical Abbreviation Candidate Inventory）

本文件用于保存项目中的轻量级医学缩写候选词典，
为医学缩写扩写流程提供候选扩展项。

设计目标：
1. 为常见临床缩写提供候选扩写
2. 支持基于上下文的缩写消歧
3. 避免完全依赖 LLM 自由生成
4. 将“缩写扩写问题”转化为“候选选择问题”

数据来源策略：
当前候选库为项目级轻量候选库，主要参考：
1. 常见临床缩写用法
2. 医学缩写消歧相关研究
3. 公开医学缩写资源，例如 MeDAL、医学缩写 Meta-Inventory 等

注意：
本文件不是完整的医学缩写数据库。
它的定位是项目中的候选召回层，用于演示、评测和系统流程验证。

后续优化方向：
1. 使用更大规模的真实医学缩写数据集替换或扩展当前词典
2. 接入 UMLS、MeDAL 或 Medical Abbreviation Meta-Inventory
3. 为每个候选扩写增加来源、频率、科室领域等元数据
"""

# 规则说明：
# 所有缩写 key 统一使用大写。
# 系统在召回候选前，会将输入缩写统一转换为大写再查表。
# 例如：输入 "htn" 或 "HTN"，最终都会查找 "HTN"。

ABBR_CANDIDATES = {
    "SOB": [
        "shortness of breath",
    ],
    "HTN": [
        "hypertension",
    ],
    "DM": [
        "diabetes mellitus",
        "dermatomyositis",
    ],
    "CP": [
        "chest pain",
        "cerebral palsy",
        "chronic pancreatitis",
    ],
    "HF": [
        "heart failure",
        "hepatic fibrosis",
    ],

    # Cardiovascular
    "CAD": [
        "coronary artery disease",
    ],
    "CHF": [
        "congestive heart failure",
    ],
    "MI": [
        "myocardial infarction",
        "mitral insufficiency",
    ],
    "CABG": [
        "coronary artery bypass grafting",
    ],
    "AF": [
        "atrial fibrillation",
        "atrial flutter",
    ],
    "AS": [
        "aortic stenosis",
        "ankylosing spondylitis",
    ],
    "MS": [
        "multiple sclerosis",
        "mitral stenosis",
    ],

    # Pulmonary
    "COPD": [
        "chronic obstructive pulmonary disease",
    ],
    "PE": [
        "pulmonary embolism",
        "physical examination",
    ],
    "PNA": [
        "pneumonia",
    ],
    "ARDS": [
        "acute respiratory distress syndrome",
    ],

    # Renal / metabolic
    "AKI": [
        "acute kidney injury",
    ],
    "CKD": [
        "chronic kidney disease",
    ],
    "ESRD": [
        "end stage renal disease",
    ],
    "DKA": [
        "diabetic ketoacidosis",
    ],

    # Neurology
    "CVA": [
        "cerebrovascular accident",
        "costovertebral angle",
    ],
    "TIA": [
        "transient ischemic attack",
    ],
    "SZ": [
        "seizure",
    ],
    "AMS": [
        "altered mental status",
    ],
    "LMN": [
        "lower motor neuron",
    ],

    # GI / hepatology
    "GI": [
        "gastrointestinal",
    ],
    "GERD": [
        "gastroesophageal reflux disease",
    ],
    "IBD": [
        "inflammatory bowel disease",
    ],
    "IBS": [
        "irritable bowel syndrome",
    ],
    "NASH": [
        "nonalcoholic steatohepatitis",
    ],

    # Infectious disease
    "UTI": [
        "urinary tract infection",
    ],
    "URI": [
        "upper respiratory infection",
    ],
    "HIV": [
        "human immunodeficiency virus",
    ],
    "TB": [
        "tuberculosis",
    ],
    "COVID": [
        "coronavirus disease",
    ],

    # Labs / clinical context
    "WBC": [
        "white blood cell count",
        "white blood cells",
    ],
    "RBC": [
        "red blood cell count",
        "red blood cells",
    ],
    "HGB": [
        "hemoglobin",
    ],
    "PLT": [
        "platelet count",
        "platelets",
    ],
    "NA": [
        "sodium",
    ],
    "K": [
        "potassium",
    ],
}