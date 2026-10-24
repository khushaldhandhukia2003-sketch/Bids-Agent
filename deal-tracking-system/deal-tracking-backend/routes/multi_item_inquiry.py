"""
routes/multi_item_inquiry.py

Endpoints:
  POST /api/inquiries/parse-and-group
  POST /api/inquiries/parse-and-group/upload
  POST /api/inquiries/master/create
  POST /api/inquiries/line-item/save
  GET  /api/inquiries/master/{inquiry_id}

  POST /api/vendors/search-log/create        ← create search log record
  POST /api/vendors/channels/detect          ← Groq detects channels for a vendor
  POST /api/vendors/save                     ← save kept vendors + channel map
  GET  /api/vendors/analytics                ← channel × team counts for dashboard
  GET  /api/vendors/analytics/export         ← CSV export of analytics
  POST /api/vendors/pipeline/log             ← log vendor selection decisions
  GET  /api/vendors/pipeline/analytics       ← channel/vendor performance stats
  GET  /api/vendors/pipeline/summary/{id}    ← decisions for a specific inquiry
"""

import os, csv, io, json, re, datetime
import shutil
from fastapi          import APIRouter, HTTPException, UploadFile, File, Depends, Header
from typing           import Optional
from fastapi.responses import StreamingResponse
from pydantic         import BaseModel
from typing           import Optional, List

from services.inquiry_parser import parse_inquiry_document, group_items_by_category
from services.documentParser import extract_text
from services.openai_fallback import parse_with_llm
from database                import get_suppliers_db

router     = APIRouter(tags=["Multi-Item Inquiry"])
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".csv",
    ".xlsx", ".xls", ".xlsm", ".xlsb",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif",
}

# All 25 channels for reference
CHANNELS = {
    "LAD": 1,  "GM": 2,   "OCD": 3,  "OEM": 4,  "ISD": 5,
    "IGS": 6,  "PSE": 7,  "LMR": 8,  "FZT": 9,  "B2B": 10,
    "HOA": 11, "SRC": 12, "BGA": 13, "CIS": 14, "MRO": 15,
    "CBN": 16, "ESP": 17, "OHF": 18, "MCR": 19, "SBP": 20,
    "PSS": 21, "RRP": 22, "ABP": 23, "PTA": 24, "SPS": 25,
}


# ── Parse / Group models ──────────────────────────────────────

class ParseTextRequest(BaseModel):
    text:     str
    filename: Optional[str] = None

class ParsedItem(BaseModel):
    description:  str
    reference:    Optional[str] = None
    quantity:     Optional[str] = None
    unit:         Optional[str] = None
    closing_date: Optional[str] = None

class CategoryGroup(BaseModel):
    category_name:      str
    category_code:      str
    suggested_channels: List[str]
    item_count:         int
    items:              List[ParsedItem]

class ParseAndGroupResponse(BaseModel):
    success:         bool
    client:          Optional[str]
    delivery:        str
    closing_date:    Optional[str]
    notes:           Optional[str]
    is_multi_item:   bool
    item_count:      int
    items:           List[ParsedItem]
    category_groups: List[CategoryGroup]
    parse_error:     Optional[str] = None


# ── Inquiry master / line item models ─────────────────────────

class CreateMasterRequest(BaseModel):
    inquiry_id:   str
    client:       Optional[str] = None
    delivery:     Optional[str] = None
    closing_date: Optional[str] = None
    notes:        Optional[str] = None
    team:         Optional[str] = None
    total_items:  int
    division_id:  Optional[int] = None
    is_draft:     bool = True   # True = in-progress, False = fully saved (visible in RFQ list)

class SaveLineItemRequest(BaseModel):
    inquiry_id:      str
    line_ref:        Optional[str] = None
    description:     str
    quantity:        Optional[str] = None
    unit:            Optional[str] = None
    category:        Optional[str] = None
    channel_codes:   Optional[str] = None
    suppliers_found: Optional[str] = None
    new_vendors:     Optional[str] = None
    rfq_count:       int = 0

class SaveSingleInquiryRequest(BaseModel):
    inquiry_id:        str
    part_number:       Optional[str] = None
    description:       Optional[str] = None
    specs:             Optional[str] = None
    quantity:          Optional[str] = None
    delivery:          Optional[str] = None
    customer:          Optional[str] = None
    team:              Optional[str] = None
    channel_codes:     Optional[str] = None
    suppliers_found:   Optional[str] = None
    new_vendors_found: Optional[str] = None
    rfq_count:         int = 0


# ── Vendor save models ────────────────────────────────────────

class CreateSearchLogRequest(BaseModel):
    search_id:          str           # e.g. SRCH-2026-001-20260407
    inquiry_id:         Optional[str] = None
    team:               Optional[str] = None
    engineer:           Optional[str] = None
    items_searched:     str
    search_mode:        str = "individual"
    channels_used:      Optional[str] = None
    db_vendors_found:   int = 0
    new_vendors_found:  int = 0

class DetectChannelsRequest(BaseModel):
    vendor_name:        str
    country:            Optional[str] = None
    description:        Optional[str] = None
    sourcing_rationale: Optional[str] = None
    source:             Optional[str] = None
    brands:             Optional[str] = None

class VendorToSave(BaseModel):
    vendor_name:         str
    country:             Optional[str] = None
    city:                Optional[str] = None
    email:               Optional[str] = None
    phone:               Optional[str] = None
    website:             Optional[str] = None
    brands:              Optional[str] = None
    description:         Optional[str] = None
    sourcing_rationale:  Optional[str] = None
    confidence_score:    Optional[float] = None
    source:              Optional[str] = None
    channel_codes:       List[str]      # e.g. ["LAD", "OEM"] — engineer-confirmed

class SaveVendorsRequest(BaseModel):
    search_id:   str
    inquiry_id:  Optional[str] = None
    vendors:     List[VendorToSave]
    team:        Optional[str] = None
    client:      Optional[str] = None


# ── Parse endpoints ───────────────────────────────────────────

@router.post("/inquiries/parse-and-group", response_model=ParseAndGroupResponse)
async def parse_and_group_text(req: ParseTextRequest):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    return _run_parse_and_group(req.text, source=req.filename or "text input")


@router.post("/inquiries/parse-and-group/upload", response_model=ParseAndGroupResponse)
async def parse_and_group_file(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type '{ext}' not supported.")
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        text = extract_text(file_path)
        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from file")
        return _run_parse_and_group(text, source=file.filename)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.post("/inquiries/parse-and-group/upload-multi", response_model=ParseAndGroupResponse)
async def parse_and_group_multi_files(files: List[UploadFile] = File(...)):
    """Accept multiple files, extract text from each and merge before parsing."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    combined_parts = []
    filenames = []
    saved_paths = []

    try:
        for file in files:
            ext = os.path.splitext(file.filename or "")[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"File type '{ext}' not supported for '{file.filename}'.")
            file_path = os.path.join(UPLOAD_DIR, file.filename)
            saved_paths.append(file_path)
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            text = extract_text(file_path)
            if text and text.strip():
                combined_parts.append(f"--- Document: {file.filename} ---\n{text.strip()}")
                filenames.append(file.filename)

        if not combined_parts:
            raise HTTPException(status_code=400, detail="Could not extract text from any of the uploaded files")

        combined_text = "\n\n".join(combined_parts)
        source_label  = ", ".join(filenames)
        return _run_parse_and_group(combined_text, source=source_label)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p in saved_paths:
            if os.path.exists(p):
                os.remove(p)


# ── Master inquiry endpoints ──────────────────────────────────

@router.post("/inquiries/master/create")
def create_master_inquiry(req: CreateMasterRequest, db=Depends(get_suppliers_db)):
    try:
        cursor = db.cursor()
        # Resolve division_id from team name if not explicitly passed
        division_id = req.division_id
        if not division_id and req.team:
            cursor.execute("SELECT id FROM divisions WHERE name = %s OR code = %s LIMIT 1",
                           (req.team, req.team))
            row = cursor.fetchone()
            if row:
                division_id = row[0]

        cursor.execute("""
            INSERT INTO inquiry_master
                (inquiry_id, client, delivery, closing_date, notes, team, total_items, division_id, is_draft)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (inquiry_id) DO UPDATE SET
                client = EXCLUDED.client, delivery = EXCLUDED.delivery,
                closing_date = EXCLUDED.closing_date, notes = EXCLUDED.notes,
                team = EXCLUDED.team, total_items = EXCLUDED.total_items,
                division_id = COALESCE(EXCLUDED.division_id, inquiry_master.division_id),
                is_draft = EXCLUDED.is_draft,
                updated_at = NOW()
        """, (req.inquiry_id, req.client, req.delivery, req.closing_date,
              req.notes, req.team, req.total_items, division_id, req.is_draft))
        db.commit(); cursor.close()
        return {"success": True, "inquiry_id": req.inquiry_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/inquiries/line-item/save")
def save_line_item(req: SaveLineItemRequest, db=Depends(get_suppliers_db)):
    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO inquiry_line_items
                (inquiry_id, line_ref, description, quantity, unit,
                 category, channel_codes, status,
                 suppliers_found, new_vendors, rfq_count, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'done', %s, %s, %s, NOW())
        """, (req.inquiry_id, req.line_ref, req.description, req.quantity,
              req.unit, req.category, req.channel_codes,
              req.suppliers_found, req.new_vendors, req.rfq_count))
        cursor.execute("""
            UPDATE inquiry_master
            SET completed_items = completed_items + 1, updated_at = NOW()
            WHERE inquiry_id = %s
        """, (req.inquiry_id,))
        db.commit(); cursor.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inquiries/master/{inquiry_id}")
def get_master_inquiry(inquiry_id: str, db=Depends(get_suppliers_db)):
    try:
        cursor = db.cursor()
        cursor.execute("SELECT * FROM inquiry_master WHERE inquiry_id = %s", (inquiry_id,))
        cols   = [d[0] for d in cursor.description]
        master = cursor.fetchone()
        if not master:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        master_dict = {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                       for k, v in zip(cols, master)}
        cursor.execute("""
            SELECT * FROM inquiry_line_items WHERE inquiry_id = %s ORDER BY created_at ASC
        """, (inquiry_id,))
        cols  = [d[0] for d in cursor.description]
        items = [{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                  for k, v in zip(cols, row)} for row in cursor.fetchall()]
        cursor.close()
        return {"success": True, "inquiry": master_dict, "items": items,
                "progress": f"{master_dict['completed_items']}/{master_dict['total_items']}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Single inquiry save ───────────────────────────────────────

@router.post("/inquiries/save")
def save_single_inquiry(req: SaveSingleInquiryRequest, db=Depends(get_suppliers_db)):
    """
    Saves a single-item inquiry to inquiry_history AND inquiry_master (so it appears in the RFQ tab).
    Called from Step 4 Save for non-multi-item inquiries.
    """
    try:
        cursor = db.cursor()

        # Save to inquiry_history (legacy — keeps history working)
        cursor.execute("""
            INSERT INTO inquiry_history
                (inquiry_id, part_number, description, specs, quantity,
                 delivery, customer, team, channel_codes,
                 suppliers_found, new_vendors_found, rfq_count, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (inquiry_id) DO UPDATE SET
                suppliers_found   = EXCLUDED.suppliers_found,
                new_vendors_found = EXCLUDED.new_vendors_found,
                rfq_count         = EXCLUDED.rfq_count
        """, (
            req.inquiry_id, req.part_number, req.description, req.specs,
            req.quantity, req.delivery, req.customer, req.team, req.channel_codes,
            req.suppliers_found, req.new_vendors_found, req.rfq_count,
        ))

        # Resolve division_id from team name
        division_id = None
        if req.team:
            cursor.execute("SELECT id FROM divisions WHERE name = %s LIMIT 1", (req.team,))
            row = cursor.fetchone()
            if row:
                division_id = row[0]

        # Also upsert into inquiry_master so the RFQ appears in the RFQ tab
        notes = req.description or req.part_number
        cursor.execute("""
            INSERT INTO inquiry_master
                (inquiry_id, client, delivery, notes, total_items, division_id, is_draft)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (inquiry_id) DO UPDATE SET
                client      = COALESCE(EXCLUDED.client,      inquiry_master.client),
                delivery    = COALESCE(EXCLUDED.delivery,    inquiry_master.delivery),
                notes       = COALESCE(EXCLUDED.notes,       inquiry_master.notes),
                division_id = COALESCE(EXCLUDED.division_id, inquiry_master.division_id),
                is_draft    = FALSE
        """, (req.inquiry_id, req.customer, req.delivery, notes, 1, division_id))

        db.commit()
        cursor.close()
        print(f"  ✅ Inquiry {req.inquiry_id} saved to history + inquiry_master")
        return {"success": True, "inquiry_id": req.inquiry_id}
    except Exception as e:
        print(f"  ❌ Inquiry save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Vendor discovery endpoints ────────────────────────────────

@router.post("/vendors/search-log/create")
def create_search_log(req: CreateSearchLogRequest, db=Depends(get_suppliers_db)):
    """
    Called when a vendor search session starts (Step 3).
    Creates one inquiry_search_log record per batch search.
    """
    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO inquiry_search_log
                (search_id, inquiry_id, team, engineer, items_searched,
                 search_mode, channels_used, db_vendors_found, new_vendors_found)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (search_id) DO UPDATE SET
                db_vendors_found  = EXCLUDED.db_vendors_found,
                new_vendors_found = EXCLUDED.new_vendors_found
        """, (req.search_id, req.inquiry_id, req.team, req.engineer,
              req.items_searched, req.search_mode, req.channels_used,
              req.db_vendors_found, req.new_vendors_found))
        db.commit(); cursor.close()
        return {"success": True, "search_id": req.search_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PipelineDecisionRequest(BaseModel):
    inquiry_id:       str
    search_id:        Optional[str] = None
    item_description: Optional[str] = None
    vendors: List[dict]             # [{vendor_name, vendor_source, channel_used, semantic_score, confidence_score, was_selected}]

@router.post("/vendors/pipeline/log")
def log_pipeline_decisions(req: PipelineDecisionRequest, db=Depends(get_suppliers_db)):
    """
    Log which vendors were shown and which were selected for an RFQ search session.
    This is the data foundation for Phase 6 self-learning.
    Called by the frontend when the user saves their vendor selection.
    """
    if not req.vendors:
        return {"success": True, "logged": 0}
    cursor = db.cursor()
    try:
        logged = 0
        for v in req.vendors:
            cursor.execute("""
                INSERT INTO pipeline_decisions
                    (inquiry_id, search_id, item_description, vendor_name,
                     vendor_source, channel_used, semantic_score,
                     confidence_score, was_selected)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                req.inquiry_id,
                req.search_id,
                req.item_description,
                v.get("vendor_name", ""),
                v.get("vendor_source"),
                v.get("channel_used"),
                v.get("semantic_score"),
                v.get("confidence_score"),
                bool(v.get("was_selected", False)),
            ))
            logged += 1
        db.commit()
        cursor.close()
        return {"success": True, "logged": logged}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vendors/pipeline/analytics")
def get_pipeline_analytics(db=Depends(get_suppliers_db)):
    """
    Aggregate channel performance across all pipeline decisions.
    Returns per-channel stats: shown, selected, won, lost, selection_rate, win_rate.
    """
    cursor = db.cursor()
    try:
        cursor.execute("""
            SELECT
                COALESCE(channel_used, 'Unknown')          AS channel,
                COUNT(*)                                    AS total_shown,
                COUNT(*) FILTER (WHERE was_selected)       AS total_selected,
                COUNT(*) FILTER (WHERE outcome = 'won')    AS total_won,
                COUNT(*) FILTER (WHERE outcome = 'lost')   AS total_lost,
                COUNT(*) FILTER (WHERE outcome IS NULL AND was_selected) AS pending,
                ROUND(AVG(semantic_score)::numeric, 3)     AS avg_semantic_score,
                MIN(decided_at)                            AS first_used,
                MAX(decided_at)                            AS last_used
            FROM pipeline_decisions
            GROUP BY channel_used
            ORDER BY total_selected DESC, total_won DESC
        """)
        cols = [d[0] for d in cursor.description]
        channels = []
        for r in cursor.fetchall():
            row = dict(zip(cols, r))
            sel   = row["total_selected"] or 0
            shown = row["total_shown"] or 1
            won   = row["total_won"] or 0
            lost  = row["total_lost"] or 0
            row["selection_rate"] = round(sel / shown * 100, 1)
            row["win_rate"]       = round(won / (won + lost) * 100, 1) if (won + lost) > 0 else None
            row["avg_semantic_score"] = float(row["avg_semantic_score"]) if row["avg_semantic_score"] else None
            if row["first_used"]: row["first_used"] = row["first_used"].isoformat()
            if row["last_used"]:  row["last_used"]  = row["last_used"].isoformat()
            channels.append(row)

        # Summary totals
        cursor.execute("""
            SELECT
                COUNT(DISTINCT inquiry_id) AS total_inquiries,
                COUNT(*)                   AS total_decisions,
                COUNT(*) FILTER (WHERE was_selected) AS total_selected,
                COUNT(*) FILTER (WHERE outcome = 'won')  AS total_won,
                COUNT(*) FILTER (WHERE outcome = 'lost') AS total_lost
            FROM pipeline_decisions
        """)
        totals = dict(zip([d[0] for d in cursor.description], cursor.fetchone()))

        # Top vendors by selection
        cursor.execute("""
            SELECT
                vendor_name,
                COUNT(*) FILTER (WHERE was_selected) AS times_selected,
                COUNT(*) FILTER (WHERE outcome = 'won') AS wins,
                COUNT(*) FILTER (WHERE outcome = 'lost') AS losses,
                ROUND(AVG(semantic_score)::numeric, 3) AS avg_score
            FROM pipeline_decisions
            WHERE was_selected = TRUE
            GROUP BY vendor_name
            ORDER BY times_selected DESC, wins DESC
            LIMIT 10
        """)
        top_vendors = [dict(zip([d[0] for d in cursor.description], r)) for r in cursor.fetchall()]
        for v in top_vendors:
            if v["avg_score"]: v["avg_score"] = float(v["avg_score"])

        cursor.close()
        return {"success": True, "channels": channels, "totals": totals, "top_vendors": top_vendors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vendors/pipeline/summary/{inquiry_id}")
def get_pipeline_summary(inquiry_id: str, db=Depends(get_suppliers_db)):
    """Get pipeline decision log for an inquiry — useful for audit and self-learning."""
    cursor = db.cursor()
    try:
        cursor.execute("""
            SELECT vendor_name, vendor_source, channel_used,
                   semantic_score, confidence_score, was_selected,
                   outcome, decided_at
            FROM pipeline_decisions
            WHERE inquiry_id = %s
            ORDER BY was_selected DESC, semantic_score DESC NULLS LAST
        """, (inquiry_id,))
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        selected   = [r for r in rows if r["was_selected"]]
        not_chosen = [r for r in rows if not r["was_selected"]]
        return {
            "success": True,
            "inquiry_id": inquiry_id,
            "total_shown": len(rows),
            "selected": selected,
            "not_chosen": not_chosen,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.post("/vendors/channels/detect")
def detect_channels_for_vendor(req: DetectChannelsRequest):
    """
    Uses Groq to auto-detect which of the 25 sourcing channels
    best describe this vendor. Returns up to 3 channel codes.
    """
    channel_list = """
LAD - Local Authorized Distributors
GM  - Grey Market / Parallel Import
OCD - Other Country Distributors
OEM - OEM Direct Factory
ISD - Industrial Surplus Dealers
IGS - Independent Global Stockists
PSE - Project Subcontractor Excess
LMR - Local Manufacturing / Reverse Engineering
FZT - Free Zone Trading Houses
B2B - Industrial B2B Marketplaces
HOA - Hidden Regional OEM Agents
SRC - Service & Repair Companies
BGA - Buying Groups / Procurement Alliances
CIS - Cross-Industry Suppliers
MRO - Online Retail / MRO E-commerce
CBN - Category-Based Supplier Networks
ESP - Emergency Supplier Panel
OHF - Obsolete / Hard-to-Find Supplier Network
MCR - Multi-Channel RFQ Strategy
SBP - Strategic Brand Partnerships
PSS - Partial Stocking Strategy
RRP - Repair + Replacement Proposals
ABP - Alternative Brand Proposal Strategy
PTA - Payment-Term Arbitrage Strategy
SPS - Supplier Performance Segmentation"""

    prompt = f"""You are a procurement channel classifier.

Given a vendor's details, identify which sourcing channels from the list below apply to them.
Return 1 to 3 channel codes that best describe how this vendor operates.

Vendor details:
- Name: {req.vendor_name}
- Country: {req.country or 'Unknown'}
- Description: {req.description or 'N/A'}
- Sourcing rationale: {req.sourcing_rationale or 'N/A'}
- Source of discovery: {req.source or 'N/A'}
- Brands handled: {req.brands or 'N/A'}

Channel options:
{channel_list}

Rules:
- Return ONLY a JSON object
- Choose 1 to 3 codes maximum
- Be specific — do not guess wildly

Return format:
{{"channels": ["LAD", "OEM"], "reasoning": "Brief one-line reason"}}"""

    try:
        raw    = parse_with_llm(prompt, max_tokens=200)
        result = json.loads(re.sub(r"```json|```", "", raw).strip())
        codes  = [c.upper() for c in result.get("channels", []) if c.upper() in CHANNELS]
        if not codes:
            codes = ["IGS"]
        return {"success": True, "channels": codes, "reasoning": result.get("reasoning", "")}
    except Exception as e:
        print(f"  Channel detect error: {e}")
        return {"success": True, "channels": ["IGS"], "reasoning": "Auto-detection fallback"}


@router.post("/vendors/save")
def save_discovered_vendors(
    req: SaveVendorsRequest,
    db=Depends(get_suppliers_db),
    x_username:  Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
):
    """
    Saves the engineer-confirmed vendors to discovered_vendors
    and their channel assignments to vendor_channel_map.
    Called from Step 5 Save button.
    """
    try:
        cursor   = db.cursor()
        saved    = 0
        skipped  = 0

        # Look up division_id and client from inquiry_master
        inq_division_id = None
        inq_client = None
        if req.inquiry_id:
            cursor.execute("SELECT division_id, client FROM inquiry_master WHERE inquiry_id = %s", (req.inquiry_id,))
            inq_row = cursor.fetchone()
            if inq_row:
                inq_division_id, inq_client = inq_row
        # Fall back to values sent directly in the request
        if not inq_division_id and req.team:
            cursor.execute("SELECT id FROM divisions WHERE name = %s OR code = %s LIMIT 1", (req.team, req.team))
            div_row = cursor.fetchone()
            if div_row:
                inq_division_id = div_row[0]
        if not inq_client and req.client:
            inq_client = req.client

        for v in req.vendors:
            # Validate channels
            valid_codes = [c for c in v.channel_codes if c.upper() in CHANNELS]
            if not valid_codes:
                valid_codes = ["IGS"]

            channel_count = len(valid_codes)
            print(f"  [save] {v.vendor_name} | email={v.email!r} | source={v.source}")

            # Insert vendor — skip if already saved for this search
            try:
                # Ensure website has https:// prefix
                raw_website = v.website or ""
                if raw_website and not raw_website.startswith("http"):
                    raw_website = "https://" + raw_website

                cursor.execute("""
                    INSERT INTO discovered_vendors
                        (vendor_name, country, city, email, phone, website,
                         brands, description, sourcing_rationale,
                         confidence_score, source, channel_count,
                         search_id, inquiry_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (vendor_name, inquiry_id) DO UPDATE SET
                        channel_count = EXCLUDED.channel_count,
                        search_id     = EXCLUDED.search_id,
                        email         = EXCLUDED.email
                    RETURNING id
                """, (
                    v.vendor_name, v.country, v.city, v.email, v.phone, raw_website,
                    v.brands, v.description, v.sourcing_rationale,
                    v.confidence_score, v.source, channel_count,
                    req.search_id, req.inquiry_id
                ))
                vendor_id = cursor.fetchone()[0]

                # Insert channel mappings
                for code in valid_codes:
                    channel_id = CHANNELS[code.upper()]
                    cursor.execute("""
                        INSERT INTO vendor_channel_map (vendor_id, channel_id, auto_detected)
                        VALUES (%s, %s, FALSE)
                        ON CONFLICT (vendor_id, channel_id) DO NOTHING
                    """, (vendor_id, channel_id))

                # ── Also write to vendors_master ─────────────────
                # For DB vendors with edited emails, force-update vendors_master
                # directly so the export always reads the latest multi-email.
                try:
                    if v.source == "database" and v.email:
                        # Direct force-update: bypass confidence check so user edits always win
                        from routes.vendor_management import _normalize as _nv
                        norm_name = _nv(v.vendor_name)
                        cursor.execute("""
                            UPDATE vendors_master SET email = %s, updated_at = NOW()
                            WHERE normalized_name = %s
                        """, (v.email, norm_name))
                        print(f"  [save] force-updated vendors_master email for {v.vendor_name!r}")
                    else:
                        from routes.vendor_management import upsert_to_master
                        master_vendor = {
                            "vendor_name":             v.vendor_name,
                            "country":                 v.country,
                            "city":                    v.city,
                            "email":                   v.email,
                            "phone":                   v.phone,
                            "website":                 v.website or "",
                            "brands":                  v.brands,
                            "description":             v.description,
                            "sourcing_rationale":      v.sourcing_rationale,
                            "channel_codes":           ", ".join(v.channel_codes) if v.channel_codes else None,
                            "source":                  "ai_discovered",
                            "discovered_vendor_id":    vendor_id,
                            "verification_method":     v.source or "ai_pipeline",
                            "verification_confidence": round(
                                (v.confidence_score / 10.0)
                                if v.confidence_score and v.confidence_score > 1
                                else (v.confidence_score or 0.5), 2
                            ),
                            "manually_overridden":     False,
                            "last_verified_date":      None,
                            "verification_notes":      f"AI discovered via {v.source or 'pipeline'}",
                            "division_id":             inq_division_id,
                            "client":                  inq_client,
                        }
                        upsert_to_master(master_vendor, db)
                except Exception as master_err:
                    print(f"  ⚠️  vendors_master upsert failed for {v.vendor_name}: {master_err}")
                    # Non-fatal — vendor is already saved to discovered_vendors

                saved += 1

            except Exception as row_err:
                print(f"  Skipping vendor {v.vendor_name}: {row_err}")
                skipped += 1
                continue

        db.commit(); cursor.close()
        print(f"  ✅ Vendors saved: {saved} | skipped: {skipped}")

        # Log to activity feed — only when user actually confirms and saves
        if saved > 0:
            try:
                from routes.history import log_activity
                # Use sourcing_rationale of first vendor as the product description
                desc = (req.vendors[0].sourcing_rationale or req.inquiry_id or "Unknown product") if req.vendors else "Unknown product"
                vendor_names = ", ".join(v.vendor_name for v in req.vendors[:5])
                if len(req.vendors) > 5:
                    vendor_names += f" +{len(req.vendors)-5} more"
                log_activity(
                    event_type="vendor_discovery",
                    title=f"Vendors Saved — {desc[:80]}",
                    detail=f"{saved} vendors confirmed & saved: {vendor_names}",
                    meta={
                        "inquiry_id": req.inquiry_id,
                        "search_id": req.search_id,
                        "saved": saved,
                        "skipped": skipped,
                        "vendors": [v.vendor_name for v in req.vendors],
                    },
                    username=x_username,
                    user_role=x_user_role,
                )
            except Exception:
                pass

        return {"success": True, "saved": saved, "skipped": skipped}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vendors/analytics")
def get_vendor_analytics(db=Depends(get_suppliers_db)):
    """
    Returns vendor counts per channel and per team for the dashboard chart.
    """
    try:
        cursor = db.cursor()

        # Vendors per channel
        cursor.execute("""
            SELECT sc.code, sc.label, sc.channel_type, COUNT(DISTINCT vcm.vendor_id) as vendor_count
            FROM sourcing_channels sc
            LEFT JOIN vendor_channel_map vcm ON vcm.channel_id = sc.id
            GROUP BY sc.id, sc.code, sc.label, sc.channel_type
            ORDER BY sc.id
        """)
        channel_rows = cursor.fetchall()
        channels_data = [
            {"code": r[0], "label": r[1], "type": r[2], "vendor_count": r[3]}
            for r in channel_rows
        ]

        # Vendors per team
        cursor.execute("""
            SELECT
                isl.team,
                sc.code,
                sc.label,
                COUNT(DISTINCT dv.id) as vendor_count
            FROM inquiry_search_log isl
            JOIN discovered_vendors dv ON dv.search_id = isl.search_id
            JOIN vendor_channel_map vcm ON vcm.vendor_id = dv.id
            JOIN sourcing_channels sc ON sc.id = vcm.channel_id
            WHERE isl.team IS NOT NULL
            GROUP BY isl.team, sc.code, sc.label
            ORDER BY isl.team, sc.code
        """)
        team_rows = cursor.fetchall()
        team_data = [
            {"team": r[0], "channel_code": r[1], "channel_label": r[2], "vendor_count": r[3]}
            for r in team_rows
        ]

        # Summary totals
        cursor.execute("SELECT COUNT(*) FROM discovered_vendors")
        total_vendors = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT search_id) FROM discovered_vendors")
        total_searches = cursor.fetchone()[0]

        cursor.close()
        return {
            "success":       True,
            "total_vendors": total_vendors,
            "total_searches": total_searches,
            "by_channel":    channels_data,
            "by_team":       team_data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vendors/analytics/export")
def export_vendor_analytics(db=Depends(get_suppliers_db)):
    """
    CSV export of all discovered vendors with their channels and team context.
    """
    try:
        cursor = db.cursor()
        cursor.execute("""
            SELECT
                dv.vendor_name,
                dv.country,
                dv.city,
                dv.email,
                dv.phone,
                dv.website,
                dv.brands,
                dv.channel_count,
                STRING_AGG(sc.code, ', ' ORDER BY sc.code) as channels,
                isl.team,
                isl.items_searched,
                dv.confidence_score,
                dv.source,
                dv.created_at::TEXT
            FROM discovered_vendors dv
            LEFT JOIN vendor_channel_map vcm ON vcm.vendor_id = dv.id
            LEFT JOIN sourcing_channels sc   ON sc.id = vcm.channel_id
            LEFT JOIN inquiry_search_log isl ON isl.search_id = dv.search_id
            GROUP BY dv.id, isl.team, isl.items_searched
            ORDER BY dv.created_at DESC
        """)
        rows = cursor.fetchall()
        cursor.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Vendor Name", "Country", "City", "Email", "Phone", "Website",
            "Brands", "Channel Count", "Channels", "Team", "Items Searched",
            "Confidence Score", "Source", "Discovered At"
        ])
        for row in rows:
            writer.writerow(row)

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=discovered_vendors.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Per-inquiry vendor Excel export (POST with email overrides) ──
class ExportWithEmailsRequest(BaseModel):
    email_overrides: dict = {}          # vendorName → "email1 / email2 / email3"
    vendors:         list = []          # full vendor list from frontend (bypasses DB query)
    inquiry_meta:    dict = {}          # client, team, delivery, closing_date, subject

@router.post("/vendors/export-with-emails/{inquiry_id}")
def export_vendors_with_emails(inquiry_id: str, req: ExportWithEmailsRequest,
                                mode: str = "combined", subject: str = "",
                                db=Depends(get_suppliers_db)):
    """Export Excel — uses frontend vendor list directly when provided, falls back to DB."""
    overrides = {k.lower(): v for k, v in req.email_overrides.items()}
    return export_vendors_for_inquiry(
        inquiry_id, mode=mode, subject=subject, db=db,
        email_overrides=overrides,
        inline_vendors=req.vendors if req.vendors else None,
        inline_meta=req.inquiry_meta if req.inquiry_meta else None,
    )


# ── Per-inquiry vendor Excel export ──────────────────────────

@router.get("/vendors/export/{inquiry_id}")
def export_vendors_for_inquiry(inquiry_id: str, mode: str = "combined", subject: str = "", db=Depends(get_suppliers_db), email_overrides: dict = None, inline_vendors: list = None, inline_meta: dict = None):
    """
    Exports all vendors (DB + AI discovered) for a specific inquiry as Excel.
    When _inline_vendors is provided the AI section is built from that list directly
    (no DB query needed — used when downloading before saving).
    Called immediately after save AND from the history page.
    One row per vendor, sorted by channel then name.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        cursor = db.cursor()

        # ── Fetch inquiry details ─────────────────────────────
        # Use inline_meta if provided (download before save), otherwise query DB
        if inline_meta:
            client       = inline_meta.get("client") or "Unknown"
            delivery     = inline_meta.get("delivery") or "UAE"
            closing_date = inline_meta.get("closing_date") or "—"
            team         = inline_meta.get("team") or "—"
            master_display = (inquiry_id, client, delivery, closing_date, team, 1, 1)
            is_single = False
        else:
            # Try inquiry_master first (multi-item), fall back to inquiry_history (single-item)
            cursor.execute("""
                SELECT inquiry_id, client, delivery, closing_date, team, total_items, completed_items
                FROM inquiry_master WHERE inquiry_id = %s
            """, (inquiry_id,))
            master = cursor.fetchone()

            if master is not None:
                client       = master[1] or "Unknown"
                delivery     = master[2] or "UAE"
                closing_date = master[3] or "—"
                team         = master[4] or "—"
                master_display = master
                is_single = False
            else:
                cursor.execute("""
                    SELECT inquiry_id, customer, delivery, NULL, team, 1, 1,
                           part_number, description, specs, quantity, suppliers_found, new_vendors_found
                    FROM inquiry_history WHERE inquiry_id = %s
                    LIMIT 1
                """, (inquiry_id,))
                hist = cursor.fetchone()
                if hist is None:
                    # No DB record yet — use a minimal fallback so download still works
                    client = "Unknown"; delivery = "UAE"; closing_date = "—"; team = "—"
                    master_display = (inquiry_id, client, delivery, closing_date, team, 1, 1)
                    is_single = False
                else:
                    client       = hist[1] or "Unknown"
                    delivery     = hist[2] or "UAE"
                    closing_date = "—"
                    team         = hist[4] or "—"
                    master_display = (inquiry_id, client, delivery, "—", team, 1, 1)
                    is_single = True

        # ── Fetch DB vendors ──────────────────────────────────
        # Multi-item: from inquiry_line_items
        # Single-item: from inquiry_history.suppliers_found
        db_vendor_names = set()

        if is_single:
            # Single inquiry — suppliers_found is in inquiry_history
            cursor.execute("""
                SELECT suppliers_found FROM inquiry_history WHERE inquiry_id = %s LIMIT 1
            """, (inquiry_id,))
            hist_row = cursor.fetchone()
            if hist_row and hist_row[0]:
                for name in hist_row[0].split(","):
                    n = name.strip()
                    if n: db_vendor_names.add(n)
        else:
            cursor.execute("""
                SELECT suppliers_found FROM inquiry_line_items
                WHERE inquiry_id = %s AND suppliers_found IS NOT NULL
            """, (inquiry_id,))
            for row in cursor.fetchall():
                if row[0]:
                    for name in row[0].split(","):
                        n = name.strip()
                        if n: db_vendor_names.add(n)

        # Fetch any email overrides saved in discovered_vendors for this inquiry
        # Look up DB vendor details — vendors_master with latest email from discovered_vendors
        db_vendors_rows = []
        if not email_overrides:
            email_overrides = {}
        if db_vendor_names:
            name_list = list(db_vendor_names)

            # 1) vendors_master — prefer latest email AND website from discovered_vendors for this inquiry
            cursor.execute("""
                SELECT vm.vendor_name, vm.country, vm.city,
                       COALESCE(dv_latest.email,   vm.email)   AS email,
                       vm.phone,
                       COALESCE(NULLIF(dv_latest.website,''), vm.website) AS website,
                       vm.brands, vm.channel_codes, NULL
                FROM vendors_master vm
                LEFT JOIN LATERAL (
                    SELECT email, website FROM discovered_vendors
                    WHERE inquiry_id = %s
                      AND LOWER(vendor_name) = LOWER(vm.vendor_name)
                    ORDER BY id DESC LIMIT 1
                ) dv_latest ON true
                WHERE LOWER(vm.vendor_name) = ANY(%s::text[])
                LIMIT 50
            """, (inquiry_id, [n.lower() for n in name_list]))
            master_rows = cursor.fetchall()
            found_in_master = {r[0].lower() for r in master_rows}

            # 2) Suppliers_Clean_Phase1 for any names not found above — also prefer discovered website/email
            remaining = [n for n in name_list if n.lower() not in found_in_master]
            legacy_rows = []
            if remaining:
                cursor.execute("""
                    SELECT s."Supplier Name", s."Country", s."City",
                           COALESCE(NULLIF(dv_latest.email,''),   s."Contact Email") AS email,
                           s."Phone",
                           COALESCE(NULLIF(dv_latest.website,''), s."Website")       AS website,
                           s."Products / Brands Handled",
                           s."Supplier Type (Group A Channel)", NULL
                    FROM "Suppliers_Clean_Phase1" s
                    LEFT JOIN LATERAL (
                        SELECT email, website FROM discovered_vendors
                        WHERE inquiry_id = %s
                          AND LOWER(vendor_name) = LOWER(s."Supplier Name")
                        ORDER BY id DESC LIMIT 1
                    ) dv_latest ON true
                    WHERE LOWER(s."Supplier Name") = ANY(%s::text[])
                    LIMIT 50
                """, (inquiry_id, [n.lower() for n in remaining]))
                legacy_rows = cursor.fetchall()

            db_vendors_rows = list(master_rows) + list(legacy_rows)

        # ── Fetch AI discovered vendors ───────────────────────
        if inline_vendors is not None:
            # Use vendor list sent directly from frontend (download before save)
            def _email_str(v):
                override = (email_overrides or {}).get((v.get("name") or "").lower())
                if override:
                    return override
                emails = v.get("emails") or []
                if not emails and v.get("email"):
                    emails = [v["email"]]
                return " / ".join(e for e in emails if e)
            ai_vendors_rows = [
                (
                    v.get("name") or "",
                    v.get("country") or "",
                    v.get("city") or "",
                    _email_str(v),
                    v.get("phone") or "",
                    v.get("website") or "",
                    v.get("brands") or "",
                    v.get("score") or v.get("confidence_score") or "",
                    v.get("channel_code") or "IGS",
                )
                for v in inline_vendors
            ]
            cursor.close()
        else:
            # Scope to the most recent search_id so re-runs don't accumulate stale vendors
            cursor.execute("""
                SELECT
                    dv.vendor_name, dv.country, dv.city, dv.email, dv.phone,
                    dv.website, dv.brands, dv.confidence_score,
                    STRING_AGG(sc.code, ', ' ORDER BY sc.code) as channels
                FROM discovered_vendors dv
                LEFT JOIN vendor_channel_map vcm ON vcm.vendor_id = dv.id
                LEFT JOIN sourcing_channels sc   ON sc.id = vcm.channel_id
                WHERE dv.inquiry_id = %s
                  AND dv.search_id = (
                      SELECT search_id FROM discovered_vendors
                      WHERE inquiry_id = %s
                      ORDER BY id DESC LIMIT 1
                  )
                GROUP BY dv.id
                ORDER BY dv.vendor_name
            """, (inquiry_id, inquiry_id))
            ai_vendors_rows = cursor.fetchall()
            cursor.close()

        # ── Build Excel workbook ──────────────────────────────
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Vendor List"

        # Styles
        hdr_font    = Font(name="Arial", bold=True, size=10, color="FFFFFF")
        hdr_fill    = PatternFill("solid", fgColor="1F3864")
        sub_fill    = PatternFill("solid", fgColor="D6E4F0")
        sub_font    = Font(name="Arial", bold=True, size=10, color="1F3864")
        body_font   = Font(name="Arial", size=9)
        alt_fill    = PatternFill("solid", fgColor="F2F7FC")
        center      = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left        = Alignment(horizontal="left",   vertical="center", wrap_text=True)
        thin_side   = Side(style="thin", color="CCCCCC")
        thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

        # ── Row 1: Title ──────────────────────────────────────
        ws.merge_cells("A1:I1")
        title_text = subject if subject.strip() else f"Vendor List — Inquiry {inquiry_id}"
        ws["A1"] = title_text
        ws["A1"].font      = Font(name="Arial", bold=True, size=13, color="1F3864")
        ws["A1"].alignment = left
        ws.row_dimensions[1].height = 22

        # ── Row 2: Inquiry metadata ───────────────────────────
        ws.merge_cells("A2:I2")
        ws["A2"] = f"Client: {client}   |   Delivery: {delivery}   |   Closing: {closing_date}   |   Team: {team}   |   Total items: {master_display[5]}   |   Completed: {master_display[6]}"
        ws["A2"].font      = Font(name="Arial", size=9, color="595959", italic=True)
        ws["A2"].alignment = left
        ws.row_dimensions[2].height = 16

        ws.row_dimensions[3].height = 8  # spacer

        # ── Row 4: Column headers ─────────────────────────────
        headers = ["#", "Vendor Name", "Country", "City", "Email", "Phone", "Website", "Brands / Products", "Channels"]
        col_widths = [4, 30, 14, 14, 28, 16, 30, 28, 20]

        for col_idx, (h, w) in enumerate(zip(headers, col_widths), 1):
            cell = ws.cell(row=4, column=col_idx, value=h)
            cell.font      = hdr_font
            cell.fill      = hdr_fill
            cell.alignment = center
            cell.border    = thin_border
            ws.column_dimensions[get_column_letter(col_idx)].width = w

        ws.row_dimensions[4].height = 18

        # ── Section: DB Vendors ───────────────────────────────
        current_row = 5

        if db_vendors_rows:
            ws.merge_cells(f"A{current_row}:I{current_row}")
            ws[f"A{current_row}"] = f"From Existing Database ({len(db_vendors_rows)} vendors)"
            ws[f"A{current_row}"].font      = sub_font
            ws[f"A{current_row}"].fill      = sub_fill
            ws[f"A{current_row}"].alignment = left
            ws[f"A{current_row}"].border    = thin_border
            ws.row_dimensions[current_row].height = 16
            current_row += 1

            for i, v in enumerate(db_vendors_rows):
                fill = alt_fill if i % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
                override = (email_overrides or {}).get(v[0].lower() if v[0] else "")
                raw_email  = override if override is not None else (v[3] or "")
                all_emails = [e.strip() for e in raw_email.replace(" / ", ",").split(",") if e.strip()]
                email_cell = " / ".join(all_emails) if all_emails else ""
                row_data = [i+1, v[0], v[1] or "", v[2] or "", email_cell, v[4] or "", v[5] or "", v[6] or "", v[7] or ""]
                for col_idx, val in enumerate(row_data, 1):
                    cell = ws.cell(row=current_row, column=col_idx, value=val)
                    cell.font      = body_font
                    cell.fill      = fill
                    cell.alignment = left if col_idx > 1 else center
                    cell.border    = thin_border
                ws.row_dimensions[current_row].height = 15
                current_row += 1

        # ── Section: AI Discovered Vendors ────────────────────
        # Exclude vendors already shown in the DB section to avoid duplicates
        db_names_lower = {r[0].lower() for r in db_vendors_rows if r[0]}
        ai_vendors_unique = [v for v in ai_vendors_rows if not (v[0] or "").lower() in db_names_lower]

        ai_fill_hdr = PatternFill("solid", fgColor="E8F5E9")
        ai_font_hdr = Font(name="Arial", bold=True, size=10, color="1B5E20")

        if ai_vendors_unique:
            ws.merge_cells(f"A{current_row}:I{current_row}")
            ws[f"A{current_row}"] = f"AI Discovered Vendors ({len(ai_vendors_unique)} vendors)"
            ws[f"A{current_row}"].font      = ai_font_hdr
            ws[f"A{current_row}"].fill      = ai_fill_hdr
            ws[f"A{current_row}"].alignment = left
            ws[f"A{current_row}"].border    = thin_border
            ws.row_dimensions[current_row].height = 16
            current_row += 1

            for i, v in enumerate(ai_vendors_unique):
                fill = alt_fill if i % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
                override = (email_overrides or {}).get(v[0].lower() if v[0] else "")
                raw_email  = override if override is not None else (v[3] or "")
                all_emails = [e.strip() for e in raw_email.replace(" / ", ",").split(",") if e.strip()]
                email_cell = " / ".join(all_emails) if all_emails else ""
                row_data = [i+1, v[0], v[1] or "", v[2] or "", email_cell, v[4] or "", v[5] or "", v[6] or "", v[8] or ""]
                row_height = 15
                for col_idx, val in enumerate(row_data, 1):
                    cell = ws.cell(row=current_row, column=col_idx, value=val)
                    cell.font      = body_font
                    cell.fill      = fill
                    cell.alignment = Alignment(horizontal="left" if col_idx > 1 else "center",
                                               vertical="center", wrap_text=True)
                    cell.border    = thin_border
                ws.row_dimensions[current_row].height = row_height
                current_row += 1

        # ── Freeze header row ─────────────────────────────────
        ws.freeze_panes = "A5"


        # ── By-item mode: add one sheet per line item ─────────────
        if mode == "by_item":
            cursor2 = db.cursor()
            cursor2.execute("""
                SELECT il.line_ref, il.description, il.suppliers_found, il.new_vendors, il.category
                FROM inquiry_line_items il WHERE il.inquiry_id = %s ORDER BY il.created_at ASC
            """, (inquiry_id,))
            line_items = cursor2.fetchall()
            cursor2.close()

            for li_idx, li in enumerate(line_items):
                li_ref, li_desc, li_db_names, li_new_names, li_cat = li
                sheet_name = f"Item {li_idx+1} - {(li_desc or '')[:20]}"[:31]
                ws2 = wb.create_sheet(title=sheet_name)

                ws2.merge_cells("A1:I1")
                ws2["A1"] = f"{li_desc or ''}"
                ws2["A1"].font = Font(name="Arial", bold=True, size=11, color="1F3864")
                ws2["A1"].alignment = left
                ws2.merge_cells("A2:I2")
                ws2["A2"] = f"Ref: {li_ref or '—'}  |  Category: {li_cat or '—'}"
                ws2["A2"].font = Font(name="Arial", size=9, italic=True, color="595959")
                ws2["A2"].alignment = left

                for col_idx, (h, w) in enumerate(zip(headers, col_widths), 1):
                    cell = ws2.cell(row=4, column=col_idx, value=h)
                    cell.font=hdr_font; cell.fill=hdr_fill; cell.alignment=center; cell.border=thin_border
                    ws2.column_dimensions[get_column_letter(col_idx)].width = w

                row_num = 5
                if li_db_names:
                    item_db = list({n.strip() for n in li_db_names.split(",") if n.strip()})
                    c3 = db.cursor()
                    c3.execute('SELECT "Supplier Name","Country","City","Contact Email","Phone","Website","Products / Brands Handled","Supplier Type (Group A Channel)" FROM "Suppliers_Clean_Phase1" WHERE "Supplier Name"=ANY(%s::text[])', (item_db,))
                    for i, v in enumerate(c3.fetchall()):
                        f2 = alt_fill if i%2==0 else PatternFill("solid", fgColor="FFFFFF")
                        for ci, val in enumerate([i+1,v[0],v[1] or "",v[2] or "",v[3] or "",v[4] or "",v[5] or "",v[6] or "",v[7] or ""],1):
                            cell=ws2.cell(row=row_num,column=ci,value=val)
                            cell.font=body_font; cell.fill=f2; cell.alignment=left if ci>1 else center; cell.border=thin_border
                        row_num+=1
                    c3.close()

                if li_new_names:
                    item_ai = list({n.strip() for n in li_new_names.split(",") if n.strip()})
                    c4 = db.cursor()
                    c4.execute("""SELECT dv.vendor_name,dv.country,dv.city,dv.email,dv.phone,dv.website,dv.brands,
                        STRING_AGG(sc.code,', ' ORDER BY sc.code)
                        FROM discovered_vendors dv
                        LEFT JOIN vendor_channel_map vcm ON vcm.vendor_id=dv.id
                        LEFT JOIN sourcing_channels sc ON sc.id=vcm.channel_id
                        WHERE dv.vendor_name=ANY(%s::text[]) AND dv.inquiry_id=%s GROUP BY dv.id""", (item_ai, inquiry_id))
                    for i, v in enumerate(c4.fetchall()):
                        f2 = alt_fill if i%2==0 else PatternFill("solid", fgColor="FFFFFF")
                        for ci, val in enumerate([i+1,v[0],v[1] or "",v[2] or "",v[3] or "",v[4] or "",v[5] or "",v[6] or "",v[7] or ""],1):
                            cell=ws2.cell(row=row_num,column=ci,value=val)
                            cell.font=body_font; cell.fill=f2; cell.alignment=left if ci>1 else center; cell.border=thin_border
                        row_num+=1
                    c4.close()

                ws2.freeze_panes = "A5"

        # ── Stream response ───────────────────────────────────
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        mode_label = "ByItem" if mode == "by_item" else "Combined"
        # Use subject as filename if provided, sanitise for file system
        if subject.strip():
            safe_subject = "".join(c if c.isalnum() or c in " _-" else "_" for c in subject.strip())
            safe_subject = safe_subject[:80]  # cap length
            filename = f"{safe_subject}_{mode_label}.xlsx"
        else:
            filename = f"Vendors_{inquiry_id}_{mode_label}.xlsx"
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        print(f"  Export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Inquiry history ───────────────────────────────────────────

@router.get("/inquiries/history")
def get_inquiry_history(db=Depends(get_suppliers_db)):
    """
    Returns all past inquiries from both inquiry_master (multi-item)
    and inquiry_history (single-item) with vendor counts.
    """
    try:
        cursor = db.cursor()

        # Multi-item inquiries from inquiry_master
        cursor.execute("""
            SELECT
                im.inquiry_id,
                im.client,
                im.team,
                im.delivery,
                im.closing_date,
                im.total_items,
                im.completed_items,
                im.created_at::TEXT,
                COUNT(DISTINCT dv.id) as new_vendor_count,
                'multi' as inquiry_type
            FROM inquiry_master im
            LEFT JOIN discovered_vendors dv ON dv.inquiry_id = im.inquiry_id
            GROUP BY im.id
            ORDER BY im.created_at DESC
        """)
        multi_rows = cursor.fetchall()
        multi_cols = [d[0] for d in cursor.description]

        # Single-item inquiries from inquiry_history
        cursor.execute("""
            SELECT
                ih.inquiry_id,
                ih.customer          as client,
                ih.team,
                ih.delivery,
                NULL                 as closing_date,
                1                    as total_items,
                1                    as completed_items,
                ih.created_at::TEXT,
                COUNT(DISTINCT dv.id) as new_vendor_count,
                'single' as inquiry_type
            FROM inquiry_history ih
            LEFT JOIN discovered_vendors dv ON dv.inquiry_id = ih.inquiry_id
            GROUP BY ih.id
            ORDER BY ih.created_at DESC
        """)
        single_rows = cursor.fetchall()
        single_cols = [d[0] for d in cursor.description]

        # Vendor import log entries
        import_rows = []
        try:
            cursor.execute("""
                SELECT id, filename, saved, updated, skipped, total_rows, imported_at::TEXT
                FROM vendor_import_log
                ORDER BY imported_at DESC
            """)
            import_cols = [d[0] for d in cursor.description]
            import_rows = [dict(zip(import_cols, r)) for r in cursor.fetchall()]
        except Exception:
            pass
        cursor.close()

        # Combine and sort by created_at descending
        all_rows = (
            [dict(zip(multi_cols, r)) for r in multi_rows] +
            [dict(zip(single_cols, r)) for r in single_rows]
        )
        all_rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)

        return {"success": True, "inquiries": all_rows, "imports": import_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Shared parse logic ────────────────────────────────────────

def _run_parse_and_group(text: str, source: str = "") -> ParseAndGroupResponse:
    print(f"\n  parse-and-group | source: {source} | {len(text)} chars")
    parsed = parse_inquiry_document(text)
    groups = group_items_by_category(parsed)

    items_out = [ParsedItem(
        description  = item["description"],
        reference    = item.get("reference"),
        quantity     = item.get("quantity"),
        unit         = item.get("unit"),
        closing_date = item.get("closing_date"),
    ) for item in parsed.get("items", [])]

    groups_out = [CategoryGroup(
        category_name      = g["category_name"],
        category_code      = g["category_code"],
        suggested_channels = g["suggested_channels"],
        item_count         = g["item_count"],
        items              = [ParsedItem(
            description  = it["description"],
            reference    = it.get("reference"),
            quantity     = it.get("quantity"),
            unit         = it.get("unit"),
            closing_date = it.get("closing_date"),
        ) for it in g.get("items", [])],
    ) for g in groups]

    return ParseAndGroupResponse(
        success         = True,
        client          = parsed.get("client"),
        delivery        = parsed.get("delivery") or "UAE",
        closing_date    = parsed.get("closing_date"),
        notes           = parsed.get("notes"),
        is_multi_item   = parsed.get("is_multi_item", False),
        item_count      = parsed.get("item_count", 0),
        items           = items_out,
        category_groups = groups_out,
        parse_error     = parsed.get("parse_error"),
    )