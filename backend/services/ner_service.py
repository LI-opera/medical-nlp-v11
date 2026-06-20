#NER = Named Entity Recognition，中文叫：命名实体识别
#这个文件做的事情就是将专业的医疗属于从一句话中抽离出来
"""
整段医疗文本
  ↓
NERService.extract_entities()
  ↓
医学实体列表"""
from transformers import pipeline
#pipeline 是HuggingFace的高级工具，作用可以快速加载模型
#这里使用task="token=classification"对一句话里的每个token做分类

class NERService:
    """
    医疗命名实体识别服务。
    作用:输入一段临床文本，输出其中识别到的医学实体。
    """
    def __init__(self):
        #创建一个医学NER识别器
        self.ner_pipeline = pipeline(
            #给每个token分类
            task="token-classification",
            #表示使用huggingface上的医学NER模型,负责识别医学实体
            model = "Clinical-AI-Apollo/Medical-NER",
            #防止把词切碎
            aggregation_strategy = "simple"
        )
    #输入一段文本识别出医学实体
    def extract_entities(self,text:str):
        raw_entities = self.ner_pipeline(text)
        #这里self.ner_pipeline返回的是一个列表。一句话里面可能有多个医学实体
        #如：
        # [
        #     {
        #         "entity_group": "SIGN_SYMPTOM",
        #         "score": 0.9876,
        #         "word": "chest pain",
        #         "start": 12,
        #         "end": 22
        #     },
        #     ....
        # ]
        entities = []
        for item in raw_entities:
            entities.append({
                "text":item["word"],
                "label":item["entity_group"],
                "score":round(float(item["score"]),4),
                "start":item["start"],
                "end":item["end"]
            })
        #_merge_adjacent_entities就是一个清洗/后处理函数
        merged_entities = self._merge_adjacent_entities(text,entities)
        return merged_entities

    def is_medical(self, text: str):
        """对孤立短语返回 (是否有医学实体, 主 label, 分数)。
        本批只用其 label 推断 domain,不做候选过滤。
        """
        if not text:
            return False, None, 0.0
        ents = self.extract_entities(text)
        if not ents:
            return False, None, 0.0
        top = max(ents, key=lambda e: e["score"])
        return True, top["label"], top["score"]

    def _merge_adjacent_entities(self,text:str,entities:list[dict]):
        """合并相邻医学实体。例如: chest + pain = chest pain"""

        #如果entitites是空的，就直接返回空列表
        if not entities:
            return[]
        #用来装已经确定好的实体
        merged = []
        #先拿第一个实体作为当前正在处理的实体
        current = entities[0]
        for next_entity in entities[1:]:
            gap_text = text[current["end"]:next_entity["start"]]

            should_merga = (
                gap_text.strip()=="" and self._can_merge(current,next_entity)
            )
            if should_merga:
                current = {
                    "text":text[current["start"]:next_entity["end"]].strip(),
                    "label": f"{current['label']}+{next_entity['label']}",
                    "score":round((current["score"]+next_entity["score"])/2,4),
                    "start":current["start"],
                    "end":next_entity["end"]
                }
            else:
                merged.append(current)
                current = next_entity
        #最后一个实体入列
        merged.append(current)
        return merged
    def _can_merge(self,left:dict,right:dict):
        """判断两个实体是否可以合并
            当前规则：身体部位+症状可以合并
        """
        merge_laberl_pairs={
            ("BIOLOGICAL_STRUCTURE", "SIGN_SYMPTOM"),
            ("BIOLOGICAL_STRUCTURE", "DISEASE_DISORDER"),
            ("SIGN_SYMPTOM", "SIGN_SYMPTOM"),
        }
        return (left["label"],right["label"]) in merge_laberl_pairs
    #存在返回True不存在返回False







#start和end是word指代词的索引可以通过text[start:end]取出对应的字符串
