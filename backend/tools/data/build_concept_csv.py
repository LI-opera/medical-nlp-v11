"""
把 OHDSI Athena 下载的 CONCEPT.csv(130万+条)筛成本项目能用的小 CSV。
你不需要懂任何医学内容——这只是按列筛行、换个格式。

用法:
  1. 把下面 INPUT_CSV 改成你下载的 CONCEPT.csv 的完整路径。
  2. python backend/tools/build_concept_csv.py
  3. 它会在 backend/data/ 生成 snomed_clinical.csv,并打印筛了多少条。

筛选规则(都是机器判断,不用你看懂概念):
  - vocabulary_id == 'SNOMED'        只要 SNOMED,不要 ICD/RxNorm 等
  - standard_concept == 'S'          只要"标准概念"(SNOMED 的规范节点)
  - invalid_reason 为空              只要还有效的
  - domain_id 属于临床域             只要疾病/症状/操作/检验/部位这些(够覆盖你的缩写)
"""
import os
import pandas as pd

# ★★★ 只改这一行:填你下载的 CONCEPT.csv 的完整路径 ★★★
INPUT_CSV = r"E:\Work\数据库-medical\vocabulary_download_v5_{e000f44a-31e7-49c1-965b-df636979f602}_1782115073798\CONCEPT.csv"   # ← 改成你的实际路径

# 输出到项目 data 目录
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
OUTPUT_CSV = os.path.join(BACKEND_DIR, "data", "snomed_clinical.csv")

# 保留的临床域(覆盖 chest pain/hypertension/pneumonia 等所有失败 case)
CLINICAL_DOMAINS = {"Condition", "Observation", "Procedure", "Measurement",
                    "Spec Anatomic Site", "Device", "Meas Value"}

# 嵌入很慢(一条一条算),太多会跑很久。先设个上限跑通;够用了再调大/去掉。
# None = 不限(筛完多少要多少);数字 = 最多保留这么多条。
MAX_ROWS = None      # 不截断,要全部临床标准概念


def main():
    print(f"读取 {INPUT_CSV} ...(130万条,可能要十几秒)")
    # Athena 的 CONCEPT.csv 是【制表符 Tab 分隔】,不是逗号;全部按字符串读,避免类型报错
    df = pd.read_csv(INPUT_CSV, sep="\t", dtype=str, keep_default_na=False, na_values=[""])
    print(f"  原始行数: {len(df):,}")

    # 逐条筛(都是机器判断)
    m = (
        (df["vocabulary_id"] == "SNOMED")
        & (df["standard_concept"] == "S")
        & (df["invalid_reason"].fillna("") == "")
        & (df["domain_id"].isin(CLINICAL_DOMAINS))
    )
    out = df[m].copy()
    print(f"  筛后行数: {len(out):,}")
    print("  各域分布:")
    for d, n in out["domain_id"].value_counts().items():
        print(f"    {n:>8,}  {d}")

    if MAX_ROWS and len(out) > MAX_ROWS:
        out = out.head(MAX_ROWS)
        print(f"  ★ 超过 MAX_ROWS={MAX_ROWS:,},截到前 {MAX_ROWS:,} 条(够跑通;想全量就把 MAX_ROWS 设 None)")

    # 转成本项目建库脚本要的 5 列;FSN 没有就用 concept_name 顶上
    out["FSN"] = out["concept_name"]
    out = out[["concept_id", "concept_name", "domain_id", "concept_code", "FSN"]]
    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"\n已写出 {OUTPUT_CSV}  共 {len(out):,} 条")
    print("下一步:把 create_milvus_db.py 的 CSV_PATH 指到这个文件,重建 Milvus。")


if __name__ == "__main__":
    main()
