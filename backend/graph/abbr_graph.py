from langgraph.graph import StateGraph, START, END

from graph.abbr_graph_state import ABBRGraphState
from graph.abbr_graph_nodes import ABBRGraphNodes


def should_continue(state: ABBRGraphState) -> str:
    """
    决定 verify 后下一步走哪里。
    """
    if state.get("success") is True:
        return "end"

    attempt = state.get("attempt", 1)
    max_retries = state.get("max_retries", 2)

    if attempt > max_retries + 1:
        return "end"

    return "reflect"


def build_abbr_graph():
    """
    构建医学缩写扩写 LangGraph 工作流。
    """
    nodes = ABBRGraphNodes()

    workflow = StateGraph(ABBRGraphState)

    workflow.add_node("expand", nodes.expand_node)
    workflow.add_node("standardize", nodes.standardize_node)
    workflow.add_node("verify", nodes.verify_node)
    workflow.add_node("reflect", nodes.reflect_node)

    workflow.add_edge(START, "expand")
    workflow.add_edge("expand", "standardize")
    workflow.add_edge("standardize", "verify")

    workflow.add_conditional_edges(
        "verify",
        should_continue,
        {
            "reflect": "reflect",
            "end": END
        }
    )

    workflow.add_edge("reflect", "standardize")

    return workflow.compile()