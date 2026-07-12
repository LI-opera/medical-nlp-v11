from utils.embedding_config import EmbeddingConfig
from utils.embedding_factory import create_embedding_model

def main():
    #向量配置参数
    config = EmbeddingConfig()
    #创建向量模型
    embedding_model = create_embedding_model(config)
    #文本
    text = "chest_pain"
    #把一段文本变成一个向量
    #embed_query()  把用户查询变成向量
    vector = embedding_model.embed_query(text)

    print("输入文本:",text)
    print("向量类型",type(vector))
    print("向量维度",len(vector))
    print("前10个向量值",vector[:10])

if __name__ == "__main__":
    main()