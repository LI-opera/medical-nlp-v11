from typing import TypedDict

class ABBRGraphState(TypedDict,total=False):
    """
    医学缩写扩写langgraph状态对象
    langgraph的核心思想是：所有节点共享同一个state,
    每个节点从state读取数据，再把自己的结果写回state
    """
    #原始输入
    original_text:str

    #当前扩写结果
    current_expanded_text:str
    current_mappings:list[dict]

    #缩写候选
    abbreviation_candidates:list[dict]

    #标准化结果
    standardization:dict
    mapping_standardizations:list[dict]

    #校验结果
    verification:dict

    #Reflection结果
    reflection_result:dict

    #控制流程
    attempt:int
    max_retries:int
    success:bool
    stop_reason:str

    #全链路追踪
    attempts:list[dict]