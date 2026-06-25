"""
Build a second source CSV for RxNorm drug concepts.

This mirrors backend/tools/build_concept_csv.py, but it does not touch the
existing SNOMED CSV or Milvus collection. It reads Athena CONCEPT.csv, filters
standard valid RxNorm Drug concepts, and writes backend/data/rxnorm_clinical.csv.

Run:
    python backend/tools/build_rxnorm_csv.py
"""
import os

import pandas as pd


INPUT_CSV = (
    r"E:\Work\数据库-medical\vocabulary_download_v5_"
    r"{c4c88598-d60c-46b2-b609-64fd902cc91c}_1782381867144\CONCEPT.csv"
)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
OUTPUT_CSV = os.path.join(BACKEND_DIR, "data", "rxnorm_clinical.csv")

MAX_ROWS = None


def main():
    print(f"Reading {INPUT_CSV} ... (tab-separated, dtype=str)")
    df = pd.read_csv(INPUT_CSV, sep="\t", dtype=str, keep_default_na=False, na_values=[""])
    print(f"  Raw rows: {len(df):,}")
    print(f"  RxNorm rows: {len(df[df['vocabulary_id'] == 'RxNorm']):,}")

    mask = (
        (df["vocabulary_id"] == "RxNorm")
        & (df["standard_concept"] == "S")
        & (df["invalid_reason"].fillna("") == "")
        & (df["domain_id"] == "Drug")
    )
    out = df[mask].copy()
    print(f"  Standard + valid + Drug rows: {len(out):,}")
    print("  concept_class distribution (top 15):")
    for concept_class, count in out["concept_class_id"].value_counts().head(15).items():
        print(f"    {count:>8,}  {concept_class}")

    ingredients = out[out["concept_class_id"] == "Ingredient"]["concept_name"].head(10).tolist()
    print(f"  Ingredient samples: {ingredients}")

    if MAX_ROWS and len(out) > MAX_ROWS:
        out = out.head(MAX_ROWS)
        print(f"  Truncated to first {MAX_ROWS:,} rows")

    out["FSN"] = out["concept_name"]
    out = out[["concept_id", "concept_name", "domain_id", "concept_code", "FSN"]]
    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

    print(f"\nWrote {OUTPUT_CSV} with {len(out):,} rows")
    print("Next: python backend/tools/rebuild_rxnorm_milvus.py")


if __name__ == "__main__":
    main()
