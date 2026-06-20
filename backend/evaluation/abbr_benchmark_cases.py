"""
医学缩略语扩展评估的基准案例
"""
ABBR_BENCHMARK_CASES = [
    {
        "id": "single_001",
        "category": "single_meaning",
        "text": "The patient denies SOB.",
        "expected_mappings": [
            {
                "abbreviation": "SOB",
                "expansion": "shortness of breath"
            }
        ]
    },
    {
        "id": "single_002",
        "category": "single_meaning",
        "text": "The patient has HTN.",
        "expected_mappings": [
            {
                "abbreviation": "HTN",
                "expansion": "hypertension"
            }
        ]
    },
    {
        "id": "single_003",
        "category": "single_meaning",
        "text": "The patient has DM.",
        "expected_mappings": [
            {
                "abbreviation": "DM",
                "expansion": "diabetes mellitus"
            }
        ]
    },
    {
        "id": "single_004",
        "category": "single_meaning",
        "text": "The patient developed AKI after dehydration.",
        "expected_mappings": [
            {
                "abbreviation": "AKI",
                "expansion": "Acute Kidney Injury"
            }
        ]
    },
    {
        "id": "single_005",
        "category": "single_meaning",
        "text": "The patient has CAD.",
        "expected_mappings": [
            {
                "abbreviation": "CAD",
                "expansion": "coronary artery disease"
            }
        ]
    },
    {
        "id": "single_006",
        "category": "single_meaning",
        "text": "The patient has CHF.",
        "expected_mappings": [
            {
                "abbreviation": "CHF",
                "expansion": "congestive heart failure"
            }
        ]
    },
    {
        "id": "single_007",
        "category": "single_meaning",
        "text": "The patient has COPD.",
        "expected_mappings": [
            {
                "abbreviation": "COPD",
                "expansion": "chronic obstructive pulmonary disease"
            }
        ]
    },
    {
        "id": "single_008",
        "category": "single_meaning",
        "text": "The patient has CKD.",
        "expected_mappings": [
            {
                "abbreviation": "CKD",
                "expansion": "chronic kidney disease"
            }
        ]
    },
    {
        "id": "single_009",
        "category": "single_meaning",
        "text": "The patient had MI last year.",
        "expected_mappings": [
            {
                "abbreviation": "MI",
                "expansion": "myocardial infarction"
            }
        ]
    },
    {
        "id": "single_010",
        "category": "single_meaning",
        "text": "The patient underwent CABG.",
        "expected_mappings": [
            {
                "abbreviation": "CABG",
                "expansion": "coronary artery bypass grafting"
            }
        ]
    },
      {
        "id": "ambiguous_001",
        "category": "ambiguous",
        "text": "The patient reports CP radiating to the left arm.",
        "expected_mappings": [
            {
                "abbreviation": "CP",
                "expansion": "chest pain"
            }
        ]
    },
    {
        "id": "ambiguous_002",
        "category": "ambiguous",
        "text": "The child has a history of CP since birth.",
        "expected_mappings": [
            {
                "abbreviation": "CP",
                "expansion": "cerebral palsy"
            }
        ]
    },
    {
        "id": "ambiguous_003",
        "category": "ambiguous",
        "text": "The patient has MS with optic neuritis and limb weakness.",
        "expected_mappings": [
            {
                "abbreviation": "MS",
                "expansion": "multiple sclerosis"
            }
        ]
    },
    {
        "id": "ambiguous_004",
        "category": "ambiguous",
        "text": "The patient has MS with a diastolic murmur.",
        "expected_mappings": [
            {
                "abbreviation": "MS",
                "expansion": "mitral stenosis"
            }
        ]
    },
    {
        "id": "ambiguous_005",
        "category": "ambiguous",
        "text": "The patient has RA with joint pain and morning stiffness.",
        "expected_mappings": [
            {
                "abbreviation": "RA",
                "expansion": "rheumatoid arthritis"
            }
        ]
    },
    {
        "id": "ambiguous_006",
        "category": "ambiguous",
        "text": "The patient is on RA for postoperative pain control.",
        "expected_mappings": [
            {
                "abbreviation": "RA",
                "expansion": "regional anesthesia"
            }
        ]
    },
    {
        "id": "ambiguous_007",
        "category": "ambiguous",
        "text": "The patient has PE with sudden shortness of breath and chest pain.",
        "expected_mappings": [
            {
                "abbreviation": "PE",
                "expansion": "pulmonary embolism"
            }
        ]
    },
    {
        "id": "ambiguous_008",
        "category": "ambiguous",
        "text": "The patient had a normal PE during the annual visit.",
        "expected_mappings": [
            {
                "abbreviation": "PE",
                "expansion": "physical examination"
            }
        ]
    },
    {
        "id": "ambiguous_009",
        "category": "ambiguous",
        "text": "The patient has ASD with social communication difficulties.",
        "expected_mappings": [
            {
                "abbreviation": "ASD",
                "expansion": "autism spectrum disorder"
            }
        ]
    },
    {
        "id": "ambiguous_010",
        "category": "ambiguous",
        "text": "The patient has ASD with a left-to-right shunt.",
        "expected_mappings": [
            {
                "abbreviation": "ASD",
                "expansion": "atrial septal defect"
            }
        ]
    },
        {
        "id": "multi_001",
        "category": "multi_abbreviation",
        "text": "The patient has SOB and HTN.",
        "expected_mappings": [
            {"abbreviation": "SOB", "expansion": "shortness of breath"},
            {"abbreviation": "HTN", "expansion": "hypertension"}
        ]
    },
    {
        "id": "multi_002",
        "category": "multi_abbreviation",
        "text": "The patient has DM and CKD.",
        "expected_mappings": [
            {"abbreviation": "DM", "expansion": "diabetes mellitus"},
            {"abbreviation": "CKD", "expansion": "chronic kidney disease"}
        ]
    },
    {
        "id": "multi_003",
        "category": "multi_abbreviation",
        "text": "The patient has CAD and CHF.",
        "expected_mappings": [
            {"abbreviation": "CAD", "expansion": "coronary artery disease"},
            {"abbreviation": "CHF", "expansion": "congestive heart failure"}
        ]
    },
    {
        "id": "multi_004",
        "category": "multi_abbreviation",
        "text": "The patient developed AKI on CKD.",
        "expected_mappings": [
            {"abbreviation": "AKI", "expansion": "Acute Kidney Injury"},
            {"abbreviation": "CKD", "expansion": "chronic kidney disease"}
        ]
    },
    {
        "id": "multi_005",
        "category": "multi_abbreviation",
        "text": "The patient has COPD and SOB.",
        "expected_mappings": [
            {"abbreviation": "COPD", "expansion": "chronic obstructive pulmonary disease"},
            {"abbreviation": "SOB", "expansion": "shortness of breath"}
        ]
    },
    {
        "id": "multi_006",
        "category": "multi_abbreviation",
        "text": "The patient has HTN, DM, and CAD.",
        "expected_mappings": [
            {"abbreviation": "HTN", "expansion": "hypertension"},
            {"abbreviation": "DM", "expansion": "diabetes mellitus"},
            {"abbreviation": "CAD", "expansion": "coronary artery disease"}
        ]
    },
    {
        "id": "multi_007",
        "category": "multi_abbreviation",
        "text": "The patient had MI and later underwent CABG.",
        "expected_mappings": [
            {"abbreviation": "MI", "expansion": "myocardial infarction"},
            {"abbreviation": "CABG", "expansion": "coronary artery bypass grafting"}
        ]
    },
    {
        "id": "multi_008",
        "category": "multi_abbreviation",
        "text": "The patient has CHF with SOB.",
        "expected_mappings": [
            {"abbreviation": "CHF", "expansion": "congestive heart failure"},
            {"abbreviation": "SOB", "expansion": "shortness of breath"}
        ]
    },
    {
        "id": "multi_009",
        "category": "multi_abbreviation",
        "text": "The patient has CP and SOB.",
        "expected_mappings": [
            {"abbreviation": "CP", "expansion": "chest pain"},
            {"abbreviation": "SOB", "expansion": "shortness of breath"}
        ]
    },
    {
        "id": "multi_010",
        "category": "multi_abbreviation",
        "text": "The patient has DM, HTN, and CKD.",
        "expected_mappings": [
            {"abbreviation": "DM", "expansion": "diabetes mellitus"},
            {"abbreviation": "HTN", "expansion": "hypertension"},
            {"abbreviation": "CKD", "expansion": "chronic kidney disease"}
        ]
    },
        {
        "id": "coverage_001",
        "category": "coverage_failed",
        "text": "The patient has XYZ.",
        "expected_mappings": []
    },
    {
        "id": "coverage_002",
        "category": "coverage_failed",
        "text": "The patient reports QQQ.",
        "expected_mappings": []
    },
    {
        "id": "coverage_003",
        "category": "low_context_abbreviation",
        "text": "The patient has ABC and SOB.",
        "expected_mappings": [
            {"abbreviation": "SOB", "expansion": "shortness of breath"}
        ]
    },
    {
        "id": "coverage_004",
        "category": "coverage_failed",
        "text": "The patient has HTN and ZZZ.",
        "expected_mappings": [
            {"abbreviation": "HTN", "expansion": "hypertension"}
        ]
    },
    {
        "id": "coverage_005",
        "category": "low_context_abbreviation",
        "text": "The patient was evaluated for LMN.",
        "expected_mappings": []
    },
    {
        "id": "coverage_006",
        "category": "low_context_abbreviation",
        "text": "The patient has DM and QRS.",
        "expected_mappings": [
            {"abbreviation": "DM", "expansion": "diabetes mellitus"}
        ]
    },
    {
        "id": "coverage_007",
        "category": "coverage_failed",
        "text": "The patient denies TUV.",
        "expected_mappings": []
    },
    {
        "id": "coverage_008",
        "category": "low_context_abbreviation",
        "text": "The patient has COPD and NOP.",
        "expected_mappings": [
            {"abbreviation": "COPD", "expansion": "chronic obstructive pulmonary disease"}
        ]
    },
    {
        "id": "coverage_009",
        "category": "low_context_abbreviation",
        "text": "The patient was admitted with AKI and RST.",
        "expected_mappings": [
            {"abbreviation": "AKI", "expansion": "Acute Kidney Injury"}
        ]
    },
    {
        "id": "coverage_010",
        "category": "coverage_failed",
        "text": "The patient has MNO.",
        "expected_mappings": []
    },
        {
        "id": "negation_001",
        "category": "negation_preservation",
        "text": "The patient denies CP.",
        "expected_mappings": [
            {"abbreviation": "CP", "expansion": "chest pain"}
        ],
        "expected_text_contains": "denies chest pain"
    },
    {
        "id": "negation_002",
        "category": "negation_preservation",
        "text": "The patient denies SOB.",
        "expected_mappings": [
            {"abbreviation": "SOB", "expansion": "shortness of breath"}
        ],
        "expected_text_contains": "denies shortness of breath"
    },
    {
        "id": "negation_003",
        "category": "negation_preservation",
        "text": "The patient has no CP.",
        "expected_mappings": [
            {"abbreviation": "CP", "expansion": "chest pain"}
        ],
        "expected_text_contains": "no chest pain"
    },
    {
        "id": "negation_004",
        "category": "negation_preservation",
        "text": "The patient has no SOB.",
        "expected_mappings": [
            {"abbreviation": "SOB", "expansion": "shortness of breath"}
        ],
        "expected_text_contains": "no shortness of breath"
    },
    {
        "id": "negation_005",
        "category": "negation_preservation",
        "text": "The patient is without CP.",
        "expected_mappings": [
            {"abbreviation": "CP", "expansion": "chest pain"}
        ],
        "expected_text_contains": "without chest pain"
    },
    {
        "id": "negation_006",
        "category": "negation_preservation",
        "text": "The patient is without SOB.",
        "expected_mappings": [
            {"abbreviation": "SOB", "expansion": "shortness of breath"}
        ],
        "expected_text_contains": "without shortness of breath"
    },
    {
        "id": "negation_007",
        "category": "negation_preservation",
        "text": "The patient denies CP but reports SOB.",
        "expected_mappings": [
            {"abbreviation": "CP", "expansion": "chest pain"},
            {"abbreviation": "SOB", "expansion": "shortness of breath"}
        ],
        "expected_text_contains": "denies chest pain"
    },
    {
        "id": "negation_008",
        "category": "negation_preservation",
        "text": "The patient denies SOB but has CP.",
        "expected_mappings": [
            {"abbreviation": "SOB", "expansion": "shortness of breath"},
            {"abbreviation": "CP", "expansion": "chest pain"}
        ],
        "expected_text_contains": "denies shortness of breath"
    },
    {
        "id": "negation_009",
        "category": "negation_preservation",
        "text": "No CP or SOB was reported.",
        "expected_mappings": [
            {"abbreviation": "CP", "expansion": "chest pain"},
            {"abbreviation": "SOB", "expansion": "shortness of breath"}
        ],
        "expected_text_contains": "no chest pain"
    },
    {
        "id": "negation_010",
        "category": "negation_preservation",
        "text": "The patient has HTN but denies CP.",
        "expected_mappings": [
            {"abbreviation": "HTN", "expansion": "hypertension"},
            {"abbreviation": "CP", "expansion": "chest pain"}
        ],
        "expected_text_contains": "denies chest pain"
    }
    
]
from evaluation.abbr_benchmark_cases_casi import CASI_BENCHMARK_CASES
ABBR_BENCHMARK_CASES = ABBR_BENCHMARK_CASES + CASI_BENCHMARK_CASES