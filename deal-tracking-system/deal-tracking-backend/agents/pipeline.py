# agents/pipeline.py
from langgraph.graph import StateGraph, END
from agents.state           import ProcurementState
from agents.agent1_inquiry  import node_agent1
from agents.agent2_supplier import node_agent2
from agents.agent3_rfq      import node_agent3

# ── Conditional edge after Agent 1 ───────────────────────────
def should_continue(state: ProcurementState) -> str:
    """
    If Agent 1 completely failed (inquiry not saved to DB)
    stop the pipeline immediately.
    Otherwise always continue to Agent 2.
    """
    if state.get("error") and not state.get("db_inquiry_saved"):
        print("[Pipeline] Hard stop — Agent 1 failed to save inquiry")
        return "end"
    return "continue"

# ── Build the LangGraph pipeline ─────────────────────────────
def build_pipeline():
    graph = StateGraph(ProcurementState)

    # Register each agent as a node
    graph.add_node("agent1", node_agent1)
    graph.add_node("agent2", node_agent2)
    graph.add_node("agent3", node_agent3)

    # Entry point
    graph.set_entry_point("agent1")

    # After Agent 1 — conditional: continue or stop
    graph.add_conditional_edges(
        "agent1",
        should_continue,
        {
            "continue": "agent2",
            "end":       END
        }
    )

    # Agent 2 → Agent 3 → END (always run both)
    graph.add_edge("agent2", "agent3")
    graph.add_edge("agent3", END)

    return graph.compile()

# ── Singleton — compiled once on import ──────────────────────
pipeline = build_pipeline()

# ── Main entry point called by FastAPI ───────────────────────
def run_pipeline(form_data: dict) -> dict:
    """
    Converts form data to initial state and runs the full pipeline.
    Called by FastAPI endpoint — returns complete result dict.
    """
    initial_state: ProcurementState = {
        # User input
        "inquiry_id":        "",
        "part_number":       form_data.get("part_number",  ""),
        "description":       form_data.get("description",  ""),
        "quantity":          form_data.get("quantity",     ""),
        "delivery":          form_data.get("delivery",     ""),
        "customer":          form_data.get("customer",     ""),
        "team":              form_data.get("team",         "EPC"),
        "engineer":          form_data.get("engineer",     ""),
        "specs":             form_data.get("specs",        ""),
        "selected_channels": form_data.get("channels",    []),
        "selected_methods":  form_data.get("methods",     []),
        # Agent outputs — all empty at start
        "parsed_specs":      None,
        "db_inquiry_saved":  None,
        "suppliers":         None,
        "supplier_count":    None,
        "rfqs":              None,
        "rfq_count":         None,
        "current_agent":     None,
        "error":             None,
        "completed":         None,
    }

    print(f"\n{'=' * 55}")
    print(f"  PIPELINE START: {form_data.get('part_number')}")
    print(f"  Team: {form_data.get('team')} | Engineer: {form_data.get('engineer')}")
    print(f"{'=' * 55}")

    result = pipeline.invoke(initial_state)

    print(f"{'=' * 55}")
    print(f"  PIPELINE DONE : {result.get('inquiry_id')}")
    print(f"  Suppliers     : {result.get('supplier_count', 0)}")
    print(f"  RFQs          : {result.get('rfq_count', 0)}")
    print(f"  Error         : {result.get('error', 'None')}")
    print(f"{'=' * 55}\n")

    return result
