# routes/procurement.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from agents.pipeline import run_pipeline
from database import get_connection
import csv
import io
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/procurement", tags=["procurement"])

# ── Request schema ────────────────────────────────────────────
class InquiryRequest(BaseModel):
    part_number:  str
    description:  str
    quantity:     str
    delivery:     str       = ""
    customer:     str       = ""
    team:         str       = "EPC"
    engineer:     str       = ""
    specs:        str       = ""
    channels:     List[str] = []
    methods:      List[str] = []

# ── Main pipeline endpoint ────────────────────────────────────
@router.post("/run")
async def run_procurement(body: InquiryRequest):
    """
    Single endpoint — triggers full 3-agent LangGraph pipeline.
    React calls this once and gets back inquiry, suppliers, and RFQs.
    """
    result = run_pipeline(body.dict())

    # Hard failure — Agent 1 could not save inquiry
    if result.get("error") and not result.get("db_inquiry_saved"):
        return {
            "success": False,
            "error":   result["error"]
        }

    # Success — return everything
    return {
        "success":        True,
        "inquiry_id":     result.get("inquiry_id"),
        "parsed_specs":   result.get("parsed_specs",   {}),
        "suppliers":      result.get("suppliers",      []),
        "supplier_count": result.get("supplier_count", 0),
        "rfqs":           result.get("rfqs",           []),
        "rfq_count":      result.get("rfq_count",      0),
        "warning":        result.get("error")  # Non-fatal errors shown as warning
    }

# ── Get all inquiries ─────────────────────────────────────────
@router.get("/inquiries")
def get_inquiries():
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM inquiries ORDER BY created_at DESC")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

# ── Get suppliers for one inquiry ────────────────────────────
@router.get("/suppliers/{inquiry_id}")
def get_suppliers(inquiry_id: str):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM suppliers WHERE inquiry_id = %s",
        (inquiry_id,)
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

# ── Get RFQs for one inquiry ──────────────────────────────────
@router.get("/rfqs/{inquiry_id}")
def get_rfqs(inquiry_id: str):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM rfq_records WHERE inquiry_id = %s",
        (inquiry_id,)
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

# ── Export RFQs as CSV ────────────────────────────────────────
@router.get("/rfqs/{inquiry_id}/export")
def export_rfqs_csv(inquiry_id: str):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM rfq_records WHERE inquiry_id = %s",
        (inquiry_id,)
    )
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    cur.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(cols)
    writer.writerows(rows)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=rfqs_{inquiry_id}.csv"}
    )

# ── Dashboard summary ─────────────────────────────────────────
@router.get("/dashboard")
def get_dashboard():
    conn = get_connection()
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM inquiries")
    total_inquiries = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM suppliers")
    total_suppliers = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM rfq_records")
    total_rfqs = cur.fetchone()[0]

    cur.execute("SELECT team, COUNT(*) FROM inquiries GROUP BY team")
    by_team = [{"team": r[0], "count": r[1]} for r in cur.fetchall()]

    cur.execute("""
        SELECT id, customer, part_number, team, engineer, status, created_at
        FROM inquiries
        ORDER BY created_at DESC
        LIMIT 10
    """)
    cols   = [d[0] for d in cur.description]
    recent = [dict(zip(cols, row)) for row in cur.fetchall()]

    cur.close()
    conn.close()

    return {
        "total_inquiries": total_inquiries,
        "total_suppliers": total_suppliers,
        "total_rfqs":      total_rfqs,
        "by_team":         by_team,
        "recent":          recent
    }