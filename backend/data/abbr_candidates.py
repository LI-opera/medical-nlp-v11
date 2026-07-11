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
import ast
from pathlib import Path

# 规则说明：
# 所有缩写 key 统一使用大写。
# 系统在召回候选前，会将输入缩写统一转换为大写再查表。
# 例如：输入 "htn" 或 "HTN"，最终都会查找 "HTN"。

ABBR_CANDIDATES = {
    "SOB": [
        {"expansion": "shortness of breath", "domain": "Condition"},
    ],
    "HTN": [
        {"expansion": "hypertension", "domain": "Condition"},
    ],
    "DM": [
        {"expansion": "diabetes mellitus", "domain": "Condition"},
        {"expansion": "dermatomyositis", "domain": "Condition"},
    ],
    "CP": [
        {"expansion": "chest pain", "domain": "Condition"},
        {"expansion": "cerebral palsy", "domain": "Condition"},
        {"expansion": "chronic pancreatitis", "domain": "Condition"},
    ],
    "HF": [
        {"expansion": "heart failure", "domain": "Condition"},
        {"expansion": "hepatic fibrosis", "domain": "Condition"},
    ],

    # Cardiovascular
    "CAD": [
        {"expansion": "coronary artery disease", "domain": "Condition"},
    ],
    "CHF": [
        {"expansion": "congestive heart failure", "domain": "Condition"},
    ],
    "MI": [
        {"expansion": "myocardial infarction", "domain": "Condition"},
        {"expansion": "mitral insufficiency", "domain": "Condition"},
    ],
    "CABG": [
        {"expansion": "coronary artery bypass grafting", "domain": "Procedure"},
    ],
    "AF": [
        {"expansion": "atrial fibrillation", "domain": "Condition"},
        {"expansion": "atrial flutter", "domain": "Condition"},
    ],
    "AS": [
        {"expansion": "aortic stenosis", "domain": "Condition"},
        {"expansion": "ankylosing spondylitis", "domain": "Condition"},
    ],
    "MS": [
        {"expansion": "multiple sclerosis", "domain": "Condition"},
        {"expansion": "mitral stenosis", "domain": "Condition"},
    ],

    # Pulmonary
    "COPD": [
        {"expansion": "chronic obstructive pulmonary disease", "domain": "Condition"},
    ],
    "PE": [
        {"expansion": "pulmonary embolism", "domain": "Condition"},
        {"expansion": "physical examination", "domain": "Observation"},
    ],
    "PNA": [
        {"expansion": "pneumonia", "domain": "Condition"},
    ],
    "ARDS": [
        {"expansion": "acute respiratory distress syndrome", "domain": "Condition"},
    ],

    # Renal / metabolic
    "AKI": [
        {"expansion": "acute kidney injury", "domain": "Condition"},
    ],
    "CKD": [
        {"expansion": "chronic kidney disease", "domain": "Condition"},
    ],
    "ESRD": [
        {"expansion": "end stage renal disease", "domain": "Condition"},
    ],
    "DKA": [
        {"expansion": "diabetic ketoacidosis", "domain": "Condition"},
    ],

    # Neurology
    "CVA": [
        {"expansion": "cerebrovascular accident", "domain": "Condition"},
        {"expansion": "costovertebral angle", "domain": "Spec Anatomic Site"},
    ],
    "TIA": [
        {"expansion": "transient ischemic attack", "domain": "Condition"},
    ],
    "SZ": [
        {"expansion": "seizure", "domain": "Condition"},
    ],
    "AMS": [
        {"expansion": "altered mental status", "domain": "Observation"},
    ],
    "LMN": [
        {"expansion": "lower motor neuron", "domain": "Spec Anatomic Site"},
    ],

    # GI / hepatology
    "GI": [
        {"expansion": "gastrointestinal", "domain": "Spec Anatomic Site"},
    ],
    "GERD": [
        {"expansion": "gastroesophageal reflux disease", "domain": "Condition"},
    ],
    "IBD": [
        {"expansion": "inflammatory bowel disease", "domain": "Condition"},
    ],
    "IBS": [
        {"expansion": "irritable bowel syndrome", "domain": "Condition"},
    ],
    "NASH": [
        {"expansion": "nonalcoholic steatohepatitis", "domain": "Condition"},
    ],

    # Infectious disease
    "UTI": [
        {"expansion": "urinary tract infection", "domain": "Condition"},
    ],
    "URI": [
        {"expansion": "upper respiratory infection", "domain": "Condition"},
    ],
    "HIV": [
        {"expansion": "human immunodeficiency virus", "domain": "Condition"},
    ],
    "TB": [
        {"expansion": "tuberculosis", "domain": "Condition"},
    ],
    "COVID": [
        {"expansion": "coronavirus disease", "domain": "Condition"},
    ],

    # Labs / clinical context
    "WBC": [
        {"expansion": "white blood cell count", "domain": "Measurement"},
        {"expansion": "white blood cells", "domain": "Measurement"},
    ],
    "RBC": [
        {"expansion": "red blood cell count", "domain": "Measurement"},
        {"expansion": "red blood cells", "domain": "Measurement"},
    ],
    "HGB": [
        {"expansion": "hemoglobin", "domain": "Measurement"},
    ],
    "PLT": [
        {"expansion": "platelet count", "domain": "Measurement"},
        {"expansion": "platelets", "domain": "Measurement"},
    ],
    "NA": [
        {"expansion": "sodium", "domain": "Measurement"},
    ],
    "K": [
        {"expansion": "potassium", "domain": "Measurement"},
    ],

    # Drugs (ingredient-level; domain=Drug → 路由到 RxNorm)
    "ASA": [
        {"expansion": "aspirin", "domain": "Drug"},
    ],
    "MTX": [
        {"expansion": "methotrexate", "domain": "Drug"},
    ],
    "APAP": [
        {"expansion": "acetaminophen", "domain": "Drug"},
    ],
    "HCTZ": [
        {"expansion": "hydrochlorothiazide", "domain": "Drug"},
    ],
    "NTG": [
        {"expansion": "nitroglycerin", "domain": "Drug"},
    ],
 
}










_ABBR_CANDIDATES_PATH = Path(__file__)
_ABBR_CANDIDATES_MTIME = _ABBR_CANDIDATES_PATH.stat().st_mtime


def reload_abbr_candidates_if_changed(force: bool = False) -> bool:
    """Reload ABBR_CANDIDATES after manual edits during development."""
    global _ABBR_CANDIDATES_MTIME

    current_mtime = _ABBR_CANDIDATES_PATH.stat().st_mtime
    if not force and current_mtime == _ABBR_CANDIDATES_MTIME:
        return False

    text = _ABBR_CANDIDATES_PATH.read_text(encoding="utf-8")
    marker = "ABBR_CANDIDATES ="
    marker_index = text.index(marker)
    tree = ast.parse(text[marker_index:])
    assignment = tree.body[0]
    if not isinstance(assignment, ast.Assign):
        raise ValueError("ABBR_CANDIDATES assignment not found.")

    refreshed = ast.literal_eval(assignment.value)
    ABBR_CANDIDATES.clear()
    ABBR_CANDIDATES.update(refreshed)
    _ABBR_CANDIDATES_MTIME = current_mtime
    return True
