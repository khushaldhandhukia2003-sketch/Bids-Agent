"""
routes/vendor_search.py
Two endpoints:
  POST /api/vendor-search/manual   ← salesperson types product name
  POST /api/vendor-search/from-rfq ← triggered after PDF upload
"""
import os
import shutil
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel
from typing import Optional
from database import get_db

from services.vendorScraper   import scrape_uae_vendors
from services.documentParser  import extract_text

router = APIRouter(prefix="/vendor-search", tags=["Vendor Search"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── Trigger 2: Manual search ──────────────────────────────────
class ManualSearchRequest(BaseModel):
    product_query:    str
    salesperson_name: Optional[str] = None
    division_id:      Optional[int] = None

@router.post("/manual")
async def manual_vendor_search(req: ManualSearchRequest, db=Depends(get_db)):
    """Salesperson manually types product → search UAE vendors"""
    if not req.product_query.strip():
        raise HTTPException(status_code=400, detail="Product query cannot be empty")

    try:
        result = scrape_uae_vendors(product_query=req.product_query)
        # Save vendors to DB
        saved = save_vendors_to_db(result["vendors"], db, req.division_id)
        result["saved_to_db"] = saved
        return {"success": True, "trigger": "manual", **result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Trigger 1: Auto from uploaded document ────────────────────
@router.post("/from-rfq")
async def search_from_rfq_document(
    file:             UploadFile = File(...),
    salesperson_name: str        = Form(None),
    division_id:      int        = Form(None),
    db=Depends(get_db)
):
    """Upload RFQ PDF/DOCX → Claude extracts product → search UAE vendors"""

    # Validate file type
    allowed = [".pdf", ".docx", ".doc", ".txt"]
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"File type {ext} not supported. Use: {allowed}")

    # Save uploaded file
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        # Extract text from document
        rfq_text = extract_text(file_path)
        if not rfq_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from document")

        # Scrape with Claude-assisted extraction
        result = scrape_uae_vendors(
            product_query=rfq_text[:100],  # fallback
            rfq_text=rfq_text
        )

        # Save vendors to DB
        saved = save_vendors_to_db(result["vendors"], db, division_id)
        result["saved_to_db"]    = saved
        result["document_name"]  = file.filename
        result["extracted_text"] = rfq_text[:500] + "..." if len(rfq_text) > 500 else rfq_text

        return {"success": True, "trigger": "auto_from_rfq", **result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up uploaded file
        if os.path.exists(file_path):
            os.remove(file_path)


# ── Save found vendors to vendors table ───────────────────────
def save_vendors_to_db(vendors: list, db, division_id: int = None) -> int:
    cursor = db.cursor()
    saved  = 0
    try:
        for v in vendors:
            if not v.get("name"):
                continue
            # Only insert if not already exists (by name)
            cursor.execute("""
                INSERT INTO vendors (name, phone, email, address, website, source, division_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (name) DO UPDATE SET
                    phone      = EXCLUDED.phone,
                    email      = EXCLUDED.email,
                    address    = EXCLUDED.address,
                    website    = EXCLUDED.website,
                    source     = EXCLUDED.source
            """, (
                v.get("name"),
                v.get("phone"),
                v.get("email"),
                v.get("address"),
                v.get("website"),
                v.get("source"),
                division_id,
            ))
            saved += 1
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"DB save error: {e}")
    finally:
        cursor.close()
    return saved


# ── Get saved vendors ─────────────────────────────────────────
@router.get("/saved")
def get_saved_vendors(
    division_id: Optional[int] = None,
    db=Depends(get_db)
):
    cursor = db.cursor()
    try:
        if division_id:
            cursor.execute("""
                SELECT * FROM vendors 
                WHERE division_id = %s 
                ORDER BY created_at DESC
            """, (division_id,))
        else:
            cursor.execute("SELECT * FROM vendors ORDER BY created_at DESC")

        columns = [desc[0] for desc in cursor.description]
        vendors = [dict(zip(columns, row)) for row in cursor.fetchall()]
        for v in vendors:
            for k, val in v.items():
                if hasattr(val, 'isoformat'):
                    v[k] = val.isoformat()
        return {"success": True, "vendors": vendors, "count": len(vendors)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()