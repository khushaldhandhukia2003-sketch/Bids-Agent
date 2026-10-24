# agents/agent3_rfq.py
import json
import time
from agents.state import ProcurementState
from services.groq_client import ask_groq
from database import get_connection

def node_agent3(state: ProcurementState) -> ProcurementState:
    """
    Agent 3 — RFQ Automation
    ─────────────────────────
    Input:  Supplier list from Agent 2
    Output: Tagged RFQ emails saved to DB
    """
    print(f"[Agent 3] Starting RFQ generation — {state.get('supplier_count', 0)} suppliers")
    state["current_agent"] = "agent3"

    # ── Skip if upstream failed ───────────────────────────
    if state.get("error") and not state.get("db_inquiry_saved"):
        print("[Agent 3] Skipping — upstream critical error")
        return state

    if not state.get("suppliers"):
        print("[Agent 3] Skipping — no suppliers found")
        state["rfqs"]      = []
        state["rfq_count"] = 0
        return state

    try:
        suppliers = state["suppliers"]
        rfqs      = []

        for i, s in enumerate(suppliers):

            # ── Generate tagged RFQ ID ────────────────────
            rfq_id = f"{state['inquiry_id']}-{s['channel_code']}"

            # ── Generate RFQ email with Groq ──────────────
            prompt = f"""
Write a professional industrial procurement RFQ email.

SENDER : Procurement Team — [Your Company Name]
TO     : {s['name']}, {s['country']}

INQUIRY REFERENCE:
- Inquiry ID   : {state['inquiry_id']}
- RFQ ID       : {rfq_id}
- Part Number  : {state['part_number']}
- Description  : {state['description']}
- Quantity     : {state['quantity']}
- Delivery     : {state['delivery']}
- End Customer : {state.get('customer', 'Our Client')}
- Specs        : {state.get('specs', 'As per standard')}

Return JSON only:
{{
  "subject": "Professional subject line — include part number and RFQ ID",
  "body":    "Complete professional email body. Must include:\\n1. Professional greeting to {s['name']}\\n2. Brief introduction as a procurement company\\n3. Clear item details: part number, description, quantity, specs\\n4. Delivery requirement with location\\n5. Request for: unit price (USD), lead time, validity period, country of origin, warranty terms\\n6. Quotation deadline: 5 business days from this email\\n7. Professional closing with [Your Company Name] placeholder"
}}
"""
            raw   = ask_groq(prompt, max_tokens=1000)
            email = json.loads(raw)

            rfq = {
                "rfq_id":        rfq_id,
                "inquiry_id":    state["inquiry_id"],
                "supplier_name": s["name"],
                "channel_code":  s["channel_code"],
                "subject":       email.get("subject", ""),
                "email_body":    email.get("body", ""),
            }
            rfqs.append(rfq)

            # ── Save each RFQ to DB immediately ───────────
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute("""
                INSERT INTO rfq_records
                    (rfq_id, inquiry_id, supplier_name,
                     channel_code, subject, email_body)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (rfq_id) DO NOTHING
            """, (
                rfq["rfq_id"],
                rfq["inquiry_id"],
                rfq["supplier_name"],
                rfq["channel_code"],
                rfq["subject"],
                rfq["email_body"]
            ))
            conn.commit()
            cur.close()
            conn.close()

            print(f"[Agent 3] RFQ {i + 1}/{len(suppliers)}: {rfq_id}")
            time.sleep(0.5)   # Respect Groq rate limit

        state["rfqs"]      = rfqs
        state["rfq_count"] = len(rfqs)
        state["completed"] = True
        print(f"[Agent 3] ✅ Generated {len(rfqs)} RFQ emails")

    except Exception as e:
        state["error"] = f"Agent 3 failed: {str(e)}"
        print(f"[Agent 3] ❌ Error: {e}")

    return state