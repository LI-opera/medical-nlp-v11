"""
CASI-grounded benchmark cases（基于真实医疗机构数据)
================================================================

数据来源(真实、权威):
  Moon S, Pakhomov S, Liu N, Ryan JO, Melton GB.
  "A sense inventory for clinical abbreviations and acronyms created using
   clinical notes and medical dictionary resources."
  J Am Med Inform Assoc (JAMIA). 2014;21(2):299-307. PMID: 23813539.
  数据集 = CASI (Clinical Abbreviation Sense Inventory),取自美国明尼苏达大学
  Fairview Health Services 四家医院的 352,267 份真实临床病历;每个缩写的义项
  经人工标注并与 UMLS / ADAM / Stedman's Medical Dictionary 核对。
  CASI 是临床缩写消歧的公开标准基准,文献普遍以 RA / MS / MI / PA / PCP 等作为
  高歧义难例。

本文件做什么:
  - 取 CASI 里真实存在、且【不在本项目 ABBR_CANDIDATES 词典】里的高频缩写,
    用它们的【真实义项】构造临床上真实可见的消歧语境。
  - 这些缩写都走 fallback(词典没有)→ 直接压测真实世界最难、且本项目评测集
    此前缺失的维度:① fallback 消歧能力;② 过度弃权(该扩的别弃)。
  - 缩写与义项来自 CASI(真实数据);句子语境为符合临床书写习惯的构造句
    (真实 CASI snippet 含 PHI、有使用限制,故此处用等价的合规语境句)。

义项正确性:以下义项均为标准医学缩写释义,可对照 CASI / UMLS 核验:
  RA  = rheumatoid arthritis / room air / right atrium
  PA  = posteroanterior / physician assistant / pulmonary artery
  PCP = primary care physician / pneumocystis pneumonia
  DC  = discharge / discontinue
  IM  = intramuscular / infectious mononucleosis
  BAL = bronchoalveolar lavage / blood alcohol level
  BM  = bowel movement / bone marrow
  ET  = endotracheal / essential tremor
  (单义、清晰)BP=blood pressure, HR=heart rate, RR=respiratory rate,
              ECG=electrocardiogram, ABG=arterial blood gas, UA=urinalysis
"""

CASI_BENCHMARK_CASES = [
    # ===== casi_ambiguous:真实多义缩写,靠上下文消歧(fallback 路径)=====
    # —— RA ——
    {
        "id": "casi_ra_room_air",
        "category": "casi_ambiguous",
        "text": "On exam the patient was breathing comfortably on RA with an oxygen saturation of 98%.",
        "expected_mappings": [{"abbreviation": "RA", "expansion": "room air"}],
    },
    {
        "id": "casi_ra_rheumatoid",
        "category": "casi_ambiguous",
        "text": "The patient has a long history of RA with symmetric joint swelling and morning stiffness.",
        "expected_mappings": [{"abbreviation": "RA", "expansion": "rheumatoid arthritis"}],
    },
    {
        "id": "casi_ra_right_atrium",
        "category": "casi_ambiguous",
        "text": "The catheter tip was advanced into the RA under fluoroscopic guidance.",
        "expected_mappings": [{"abbreviation": "RA", "expansion": "right atrium"}],
    },
    # —— PA ——
    {
        "id": "casi_pa_posteroanterior",
        "category": "casi_ambiguous",
        "text": "A PA and lateral chest radiograph were obtained.",
        "expected_mappings": [{"abbreviation": "PA", "expansion": "posteroanterior"}],
    },
    {
        "id": "casi_pa_physician_assistant",
        "category": "casi_ambiguous",
        "text": "The patient was seen by the PA in clinic for a routine follow-up visit.",
        "expected_mappings": [{"abbreviation": "PA", "expansion": "physician assistant"}],
    },
    {
        "id": "casi_pa_pulmonary_artery",
        "category": "casi_ambiguous",
        "text": "Elevated PA pressures were noted on right heart catheterization.",
        "expected_mappings": [{"abbreviation": "PA", "expansion": "pulmonary artery"}],
    },
    # —— PCP ——
    {
        "id": "casi_pcp_primary_care",
        "category": "casi_ambiguous",
        "text": "The patient was referred by their PCP for further evaluation of the abnormal labs.",
       "expected_mappings": [{"abbreviation": "PCP", "expansion": "primary care physician",
                               "accept": ["primary care provider"]}],
    },
    {
        "id": "casi_pcp_pneumonia",
        "category": "casi_ambiguous",
        "text": "The immunocompromised patient developed PCP with bilateral interstitial infiltrates and hypoxia.",
        "expected_mappings": [{"abbreviation": "PCP", "expansion": "pneumocystis pneumonia",
                               "accept": ["pneumocystis jirovecii pneumonia", "pneumocystis carinii pneumonia"]}],
    },
    # —— DC ——
    {
        "id": "casi_dc_discharge",
        "category": "casi_ambiguous",
        "text": "The patient was clinically stable and ready for DC home with outpatient follow-up.",
        "expected_mappings": [{"abbreviation": "DC", "expansion": "discharge"}],
    },
    {
        "id": "casi_dc_discontinue",
        "category": "casi_ambiguous",
        "text": "Given the new rash, the decision was made to DC the antibiotic.",
        "expected_mappings": [{"abbreviation": "DC", "expansion": "discontinue"}],
    },
    # —— IM ——
    {
        "id": "casi_im_intramuscular",
        "category": "casi_ambiguous",
        "text": "The vaccine was administered IM into the deltoid.",
        "expected_mappings": [{"abbreviation": "IM", "expansion": "intramuscular"}],
    },
    {
        "id": "casi_im_mononucleosis",
        "category": "casi_ambiguous",
        "text": "The young adult presented with fatigue, fever, and pharyngitis consistent with IM.",
        "expected_mappings": [{"abbreviation": "IM", "expansion": "infectious mononucleosis"}],
    },
    # —— BAL ——
    {
        "id": "casi_bal_lavage",
        "category": "casi_ambiguous",
        "text": "Bronchoscopy with BAL was performed to evaluate the persistent infiltrate.",
        "expected_mappings": [{"abbreviation": "BAL", "expansion": "bronchoalveolar lavage"}],
    },
    {
        "id": "casi_bal_alcohol",
        "category": "casi_ambiguous",
        "text": "The patient's BAL was 0.18 on arrival to the emergency department after the collision.",
        "expected_mappings": [{"abbreviation": "BAL", "expansion": "blood alcohol level"}],
    },
    # —— BM ——
    {
        "id": "casi_bm_bowel",
        "category": "casi_ambiguous",
        "text": "The patient reported a normal BM this morning without blood or melena.",
        "expected_mappings": [{"abbreviation": "BM", "expansion": "bowel movement"}],
    },
    {
        "id": "casi_bm_marrow",
        "category": "casi_ambiguous",
        "text": "The BM biopsy showed hypercellularity with blasts consistent with acute leukemia.",
        "expected_mappings": [{"abbreviation": "BM", "expansion": "bone marrow"}],
    },
    # —— ET ——
    {
        "id": "casi_et_endotracheal",
        "category": "casi_ambiguous",
        "text": "The patient was intubated with a 7.5 ET tube and placed on the ventilator.",
        "expected_mappings": [{"abbreviation": "ET", "expansion": "endotracheal"}],
    },
    {
        "id": "casi_et_tremor",
        "category": "casi_ambiguous",
        "text": "The patient has a long history of ET with a bilateral action tremor of the hands.",
        "expected_mappings": [{"abbreviation": "ET", "expansion": "essential tremor"}],
    },

    # ===== fallback_should_expand:真实单义、非词典缩写 → 应扩(过度弃权探测器)=====
    {
        "id": "casi_fb_bp",
        "category": "fallback_should_expand",
        "text": "The patient's BP was elevated at 160/95 mmHg on arrival.",
        "expected_mappings": [{"abbreviation": "BP", "expansion": "blood pressure"}],
    },
    {
        "id": "casi_fb_hr",
        "category": "fallback_should_expand",
        "text": "The patient's HR was 110 beats per minute and regular.",
        "expected_mappings": [{"abbreviation": "HR", "expansion": "heart rate"}],
    },
    {
        "id": "casi_fb_rr",
        "category": "fallback_should_expand",
        "text": "The patient's RR was 24 breaths per minute with mild accessory muscle use.",
        "expected_mappings": [{"abbreviation": "RR", "expansion": "respiratory rate"}],
    },
    {
        "id": "casi_fb_ecg",
        "category": "fallback_should_expand",
        "text": "The ECG showed ST-segment elevation in the inferior leads.",
        "expected_mappings": [{"abbreviation": "ECG", "expansion": "electrocardiogram"}],
    },
    {
        "id": "casi_fb_abg",
        "category": "fallback_should_expand",
        "text": "The ABG revealed respiratory acidosis with hypoxemia.",
        "expected_mappings": [{"abbreviation": "ABG", "expansion": "arterial blood gas"}],
    },
    {
        "id": "casi_fb_ua",
        "category": "fallback_should_expand",
        "text": "The UA showed pyuria and bacteriuria.",
        "expected_mappings": [{"abbreviation": "UA", "expansion": "urinalysis"}],
    },
]
