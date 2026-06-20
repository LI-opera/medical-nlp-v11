#factory文件真正加载这个模型

#langchain封装好的HuggingFaceEmbedding类
from langchain_huggingface import HuggingFaceEmbeddings
#引入向量模型的配置文件
from utils.embedding_config import EmbeddingProvider,EmbeddingConfig

#根据配置创建对应的向量模型
#config 这个参数，应该是一个 EmbeddingConfig 类型的对象。类似：name:str
def create_embedding_model(config:EmbeddingConfig):
    """
    根据配置创建Emebdding模型
    当前版本只支持HuggingFace,后面可以增加其他模型的分支
    """
    if config.provider == EmbeddingProvider.HUGGINGFACE:
        return HuggingFaceEmbeddings(
            model_name=config.model_name,
            model_kwargs={
                "device":"auto",
                "trust_remote_code":True
            },
            #模型向量归一化
            encode_kwargs={
                "normalize_embeddings":True
            }
        )
    #如果传进来的 provider 不是当前支持的 HuggingFace，就直接报错。
    raise ValueError(f"Unsupported embedding provider:{config.provider}")