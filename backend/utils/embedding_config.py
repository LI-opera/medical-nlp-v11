#用来声明向量模型参数

#用来快速创建配置类
from dataclasses import dataclass
#Enum用来创建固定选项
from enum import Enum

# Enum = 限制只能选固定几个
# str = 这些选项的真实值是字符串
# (str, Enum) = 固定字符串选项
#provider：用哪个平台提供 embedding，目前默认是 huggingface
#Embedding 模型来源。
class EmbeddingProvider(str,Enum):
    HUGGINGFACE = "huggingface"

"""
@dataclass 的意思是：让 Python 自动帮你生成初始化方法。
如果没有dataclass，则需要自己写入初始化方法
class EmbeddingConfig:
    def __init__(self, provider, model_name):
        self.provider = provider
        self.model_name = model_name
"""
@dataclass
#Embedding 配置类。
class EmbeddingConfig:
    #服务商来自EmbeddingProvider.HUGGINGFACE
    provider:EmbeddingProvider = EmbeddingProvider.HUGGINGFACE
    #默认使用模型
    model_name:str = "BAAI/bge-m3"



"""以后别的文件会这样用它：

config = EmbeddingConfig()

等于：

config.provider = "huggingface"
config.model_name = "BAAI/bge-m3"""