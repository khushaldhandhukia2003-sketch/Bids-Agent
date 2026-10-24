# agents/state.py
from typing import TypedDict, List, Optional

class ProcurementState(TypedDict):
    # ── Input from user ──────────────────────────────────
    inquiry_id:        str
    part_number:       str
    description:       str
    quantity:          str
    delivery:          str
    customer:          str
    team:              str
    engineer:          str
    specs:             str
    selected_channels: List[str]
    selected_methods:  List[str]

    # ── Agent 1 output ───────────────────────────────────
    parsed_specs:      Optional[dict]
    db_inquiry_saved:  Optional[bool]

    # ── Agent 2 output ───────────────────────────────────
    suppliers:         Optional[List[dict]]
    supplier_count:    Optional[int]

    # ── Agent 3 output ───────────────────────────────────
    rfqs:              Optional[List[dict]]
    rfq_count:         Optional[int]

    # ── Pipeline control ─────────────────────────────────
    current_agent:     Optional[str]
    error:             Optional[str]
    completed:         Optional[bool]