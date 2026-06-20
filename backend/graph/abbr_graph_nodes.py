from services.abbr_service import ABBRService
from graph.abbr_graph_state import ABBRGraphState

class ABBRGraphNodes:
    """
    langgraph节点集合
    复用现有ABBRService的稳定V9能力
    """
    def __init__(self):
        self.service = ABBRService()

    def expand_node(self,state:ABBRGraphState)-> ABBRGraphState:
        """
        节点1：缩写扩写节点
        对应原来的
        current_expansion_result = self.simple_llm_expansion(text)
        """
        original_text = state["original_text"]

        expansion_result = self.service.simple_llm_expansion(original_text)

        return{
            **state,
            "current_expanded_text":expansion_result["expanded_text"],
            "current_mappings":expansion_result.get("mappings",[]),
            "abbreviation_candidates":expansion_result.get("abbreviation_candidates",[]),
        }
    
    def standardize_node(self,state:ABBRGraphState)->ABBRGraphState:
        """
        节点2“标准化节点。
        对应原来的:
        1.standardizer.standardize(current_expanded_text)
        2.对每个mapping的expansion做SNOMED Retrieval
        """
        current_expanded_text = state["current_expanded_text"]
        current_mappings = state.get("current_mappings",[])

        standardization_result = self.service.standardizer.standardize(
            current_expanded_text
        )

        mapping_standardizations = []

        for mapping in current_mappings:
            expansion = mapping.get("expansion")

            if not expansion:
                continue

            docs = self.service.retriever.retrieve(
                query=expansion,
                top_k=10,
                domain_filter=None,
                score_threshold=0.6
            )

            candidates = []

            for doc in docs[:3]:
                metadata = doc["metadata"]

                candidates.append({
                    "concept_id": metadata["concept_id"],
                    "concept_name": metadata["concept_name"],
                    "domain_id": metadata["domain_id"],
                    "concept_code": metadata["concept_code"],
                    "score": metadata["score"],
                    "rerank_score": metadata.get("rerank_score")
                })
            mapping_standardizations.append({
                "abbreviation": mapping["abbreviation"],
                "expansion": expansion,
                "candidates": candidates
            })
        return {
            **state,
            "standardization":standardization_result,
            "mapping_standardizations":mapping_standardizations,
        }
    
    def verify_node(self, state: ABBRGraphState) -> ABBRGraphState:
        """
        节点3：校验节点。

        对应原来的：
        self.verifier.verify_mappings(...)
        """
        original_text = state["original_text"]
        current_expanded_text = state["current_expanded_text"]
        mapping_standardizations = state.get("mapping_standardizations", [])

        verification = self.service.verifier.verify_mappings(
            original_text=original_text,
            expanded_text=current_expanded_text,
            mapping_standardizations=mapping_standardizations
        )

        attempt_result = {
            "attempt": state.get("attempt", 1),
            "expanded_text": current_expanded_text,
            "abbreviation_candidates": state.get("abbreviation_candidates", []),
            "mappings": state.get("current_mappings", []),
            "standardization": state.get("standardization"),
            "mapping_standardizations": mapping_standardizations,
            "verification": verification
        }

        attempts = state.get("attempts", [])
        attempts.append(attempt_result)

        success = verification.get("overall_valid") is True

        return {
            **state,
            "verification": verification,
            "success": success,
            "attempts": attempts,
        }
    
    def reflect_node(self, state: ABBRGraphState) -> ABBRGraphState:
        """
        节点4：反思修正节点

        当 verify_node 不通过时，根据 verification 结果和候选重新生成扩写。
        对应 ABBRReflectionService。
        """
        if state.get("success", False):
            # 如果已经成功，不需要反思
            return state

        original_text = state["original_text"]
        previous_expanded_text = state.get("current_expanded_text", "")
        verification = state.get("verification", {})
        abbreviation_candidates = state.get("abbreviation_candidates", [])

        # 调用反思服务
        reflection_result = self.service.reflector.reflect(
            original_text=original_text,
            previous_expanded_text=previous_expanded_text,
            verification=verification,
            abbreviation_candidates=abbreviation_candidates
        )

        # 更新 state
        current_expanded_text = reflection_result.get("revised_expanded_text", previous_expanded_text)
        current_mappings = reflection_result.get("revised_mappings", [])

        attempt_result = {
            "attempt": state.get("attempt", 1),
            "expanded_text": current_expanded_text,
            "abbreviation_candidates": abbreviation_candidates,
            "mappings": current_mappings,
            "reflection_result": reflection_result,
            "verification": verification
        }

        attempts = state.get("attempts", [])
        attempts.append(attempt_result)

        # 判断成功与否
        success = bool(current_mappings) and verification.get("overall_valid", False)

        next_attempt = state.get("attempt", 1) + 1
        return {
            **state,
            "current_expanded_text": current_expanded_text,
            "current_mappings": current_mappings,
            "reflection_result": reflection_result,
            "success": success,
            "attempt": next_attempt,
            "attempts": attempts
        }