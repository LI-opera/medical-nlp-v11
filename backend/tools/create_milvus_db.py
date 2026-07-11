#旧的医疗数据实体库版本可以删除
# 读取 snomed_sample.csv
#     ↓
# 取出 concept_name
#     ↓
# 用 embedding 模型转成向量
#     ↓
# 创建 Milvus Lite 数据库
#     ↓
# 把 id、名称、编码、向量 存进去

#用来处理路径
import os
#sys经常表示Python的模块搜索路径，如:sys.path
import sys
#pandas用来读csv，将csv读成DataFrame
import pandas as pd
#导入Milvus客户端
#MilvusClient负责连接 Milvus、创建 collection、插入、搜索
#DataType负责声明字段类型
from pymilvus import MilvusClient,DataType

#让当前脚本可以导入backend里的utils中的文件
#__file__当前文件的路径，os.path.abspath(__file__)获得绝对路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
#获得backend文件夹
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
#将backend文件夹加入python的模块搜索路径
sys.path.append(BACKEND_DIR)

#导入项目工具
#embedding配置
from utils.embedding_config import EmbeddingConfig
#embedding模型的创建
from utils.embedding_factory import create_embedding_model

#CSV文件地址
CSV_PATH = os.path.join(BACKEND_DIR,"data","SNOMED_5000.csv")
#集合名称
COLLECTION_NAME = "concepts_only_name"

def main():
    print("读取CSV数据")
    #读完之后df是一张表
    df = pd.read_csv(CSV_PATH)
    print("创建embedding模型")
    embedding_model = create_embedding_model(EmbeddingConfig())

    print("测试向量维度")
    test_vector = embedding_model.embed_query("test")
    vector_dim = len(test_vector)
    print("向量维度:",vector_dim)

    print("链接Milvus")
    client = MilvusClient(uri="http://127.0.0.1:19530")
    #检查是否之前创建过相同的集合
    if client.has_collection(COLLECTION_NAME):
        print("已有collection先删除旧的")
        client.drop_collection(COLLECTION_NAME)
    
    #创建表结构
    print("创建collection schema")
    schema = MilvusClient.create_schema(
        #主键不让Milvus生成
        auto_id=False,
        #不允许插入schema之外的字段
        enable_dynamic_field=False
    )
    fields =[
        {"field_name":"id","datatype":DataType.INT64,"is_primary":True},
        {"field_name":"concept_id","datatype":DataType.VARCHAR,"max_length":64},
        {"field_name":"concept_name","datatype":DataType.VARCHAR,"max_length":512},
        {"field_name":"domain_id","datatype":DataType.VARCHAR,"max_length":128},
        {"field_name":"concept_code","datatype":DataType.VARCHAR,"max_length":128},
        {"field_name":"vector","datatype":DataType.FLOAT_VECTOR,"dim":vector_dim},
        {"field_name":"FSN","datatype":DataType.VARCHAR,"max_length":2048}
    ]
    for field in fields:
        #**field 的意思是把字典拆成参数。
        schema.add_field(**field)

    #创建索引
    print("创建向量索引")
    index_params = client.prepare_index_params()
    #创建索引对象
    index_params.add_index(
        #创建索引的字段
        field_name="vector",
        #表示让 Milvus 自动选择合适索引。
        index_type="AUTOINDEX",
        #相似度计算方式用余弦相似度
        metric_type="COSINE"
    )

    print("创建 collection")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params
    )

    print("生成并插入向量数据")
    data=[]
    #遍历csv的每一行。idx 是行号。row 是这一行的数据。
    for idx,row in df.iterrows():
        concept_name = str(row["concept_name"])
        vector = embedding_model.embed_query(concept_name)
        
        data.append({
            "id":int(idx),
            "concept_id":str(row["concept_id"]),
            "concept_name":concept_name,
            "domain_id":str(row["domain_id"]),
            "concept_code":str(row["concept_code"]),
            #is + na  :NA = Not Available 判断后面括号中是否是空值
            "FSN":"" if pd.isna(row["FSN"]) else str(row["FSN"]),
            "vector":vector
        })
    result = client.insert(
        collection_name=COLLECTION_NAME,
        data=data
    )
    #把刚 insert 的数据强制刷到 Milvus 存储里。
    client.flush(collection_name=COLLECTION_NAME)
    #把这个 collection 加载到内存里，让它可以被搜索。
    client.load_collection(collection_name=COLLECTION_NAME)
    print("插入完成:")
    print(result)

    print("测试搜索 chest pain")
    query_vector = embedding_model.embed_query("chest pain")

    search_result = client.search(
        #在这个集合中搜
        collection_name=COLLECTION_NAME,
        #因为Milvus支持一次搜索多个query_vector
        data=[query_vector],
        #表示用哪个向量字段进行近似最近邻搜索。
        anns_field="vector",
        limit=3,
        output_fields=[
            "concept_id",
            "concept_name",
            "domain_id",
            "concept_code",
            "FSN"
        ]
    )
    
    #因为本身search_result支持查询多个问题。这里只是传入一个问题所有用[0]
    for i,item in enumerate(search_result[0],start=1):
        entity = item["entity"]

        print(f"Top {i}")
        print("concept_name:", entity["concept_name"])
        print("concept_id:", entity["concept_id"])
        print("domain_id:", entity["domain_id"])
        print("concept_code:", entity["concept_code"])
        print("score:", item["distance"])
        print("-" * 50)

if __name__ == "__main__":
    main()

"""
1. 创建 collection
2. 插入数据 insert
3. flush，确保数据写入完成
4. load_collection，让 collection 可搜索
5. search
"""