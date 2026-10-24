# agents/agent1_inquiry.py
import json
import random
from agents.state import ProcurementState
from services.groq_client import ask_groq
from database import get_connection

def generate_inquiry_id() -> str:
    n = random.randint(100, 999)
    return f"INQ-2026-{n:03d}"

def node_agent1(state: ProcurementState) -> ProcurementState:
    """
    Agent 1 — Inquiry Processing
    ─────────────────────────────
    Input:  Raw form data from user
    Output: Parsed specs + inquiry saved to DB
    Hands off to: Agent 2
    """
    print(f"[Agent 1] Starting — Part: {state['part_number']}")
    state["current_agent"] = "agent1"

    try:
        # ── Step 1: Generate Inquiry ID ──────────────────
        inquiry_id = generate_inquiry_id()
        state["inquiry_id"] = inquiry_id
        print(f"[Agent 1] Generated ID: {inquiry_id}")

        # ── Step 2: Parse specs with Groq ────────────────
        prompt = f"""
Parse this procurement inquiry and extract structured information.

Part Number : {state['part_number']}
Description : {state['description']}
Specs/Notes : {state['specs']}

Return JSON only:
{{
  "brand":            "extracted brand name or empty string",
  "voltage":          "voltage specification or empty string",
  "power_rating":     "power rating or empty string",
  "certifications":   "certifications or empty string",
  "key_specs":        "2-3 most important specs as a single string",
  "urgency":          "normal or urgent or emergency",
  "product_category": "product type e.g. VFD Drive, PLC, Pressure Sensor"
}}
"""
        raw    = ask_groq(prompt)
        parsed = json.loads(raw)
        state["parsed_specs"] = parsed
        print(f"[Agent 1] Parsed: {parsed.get('product_category')} | Urgency: {parsed.get('urgency')}")

        # ── Step 3: Save inquiry to PostgreSQL ────────────
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO inquiries
                (id, customer, part_number, description,
                 quantity, delivery, team, engineer, specs, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            inquiry_id,
            state.get("customer", ""),
            state["part_number"],
            state["description"],
            state["quantity"],
            state.get("delivery", ""),
            state.get("team", "EPC"),
            state.get("engineer", ""),
            json.dumps(parsed),
            "Open"
        ))
        conn.commit()
        cur.close()
        conn.close()

        state["db_inquiry_saved"] = True
        print(f"[Agent 1] ✅ Saved to DB — {inquiry_id}")

    except Exception as e:
        state["error"]            = f"Agent 1 failed: {str(e)}"
        state["db_inquiry_saved"] = False
        print(f"[Agent 1] ❌ Error: {e}")

    return state