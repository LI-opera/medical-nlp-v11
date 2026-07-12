import os
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)

CSV_PATH = os.path.join(BACKEND_DIR,"data","SNOMED_5000.csv")

def main():
    df = pd.read_csv(CSV_PATH)
    print("数据行数:",len(df))
    print("字段列表:")
    print(df.columns.tolist())

    print("\n前5行数据:")
    print(df.head())

    print("\n每一列的空值数量:")
    print(df.isnull().sum())

if __name__ == "__main__":
    main()