
ABBR_EVAL_CASES = [
    {
        "id": "case_001",
        "text": "The patient denies SOB.",
        "expected_mappings": [
            {
                "abbreviation": "SOB",
                "expansion": "shortness of breath"
            }
        ]
    },
    {
        "id": "case_002",
        "text": "The patient reports CP.",
        "expected_mappings": [
            {
                "abbreviation": "CP",
                "expansion": "chest pain"
            }
        ]
    },
    {
        "id": "case_003",
        "text": "The child has a history of CP since birth.",
        "expected_mappings": [
            {
                "abbreviation": "CP",
                "expansion": "cerebral palsy"
            }
        ]
    },
    {
        "id": "case_004",
        "text": "The patient has SOB, DM, and HTN.",
        "expected_mappings": [
            {
                "abbreviation": "SOB",
                "expansion": "shortness of breath"
            },
            {
                "abbreviation": "DM",
                "expansion": "diabetes mellitus"
            },
            {
                "abbreviation": "HTN",
                "expansion": "hypertension"
            }
        ]
    },
    {
        "id": "case_005",
        "text": "The patient developed AKI after dehydration.",
        "expected_mappings": [
            {
                "abbreviation": "AKI",
                "expansion": "Acute Kidney Injury"
            }
        ]
    },
    {
        "id": "case_006",
        "text": "The patient has XYZ.",
        "expected_mappings": []
    }
]