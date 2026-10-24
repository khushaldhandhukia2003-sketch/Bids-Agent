"""
routes/supplier_search.py
Part 1 of Agent 2 — search existing supplier database
Endpoint: POST /api/suppliers/search

Queries two sources in parallel:
  1. Suppliers_Clean_Phase1 — legacy archive (unverified, broad coverage)
  2. vendors_master          — verified database (manual imports + AI-verified)

vendors_master results appear first in the merged list since they are verified.
Deduplication prevents the same company appearing from both sources.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from database import get_suppliers_db

router = APIRouter(prefix="/suppliers", tags=["Supplier Search"])

# ── Channel name map (code → full name as stored in DB) ──────
CHANNEL_MAP = {
    "LAD":  "Local Authorized Distributors",
    "GM":   "Grey Market / Parallel Import",
    "OCD":  "Other Country Distributors",
    "OEM":  "OEM Direct Factory",
    "ISD":  "Industrial Surplus Dealers",
    "IGS":  "Independent Global Stockists",
    "PSE":  "Project Subcontractor Excess",
    "LMR":  "Local Manufacturing / Reverse Engineering",
    "FZT":  "Free Zone Trading Houses",
    "B2B":  "Industrial B2B Marketplaces",
    "HOA":  "Hidden Regional OEM Agents",
    "SRC":  "Service & Repair Companies",
    "BGA":  "Buying Groups / Procurement Alliances",
    "CIS":  "Cross-Industry Suppliers",
    "MRO":  "Online Retail / MRO E-commerce",
    "CBS":  "Category-Based Supplier Networks",
    "ESP":  "Emergency Supplier Panel",
    "OBS":  "Obsolete / Hard-to-Find Supplier Network",
    "MCR":  "Multi-Channel RFQ Strategy",
    "SBP":  "Strategic Brand Partnerships",
    "PSS":  "Partial Stocking Strategy",
    "RRP":  "Repair + Replacement Proposals",
    "ABP":  "Alternative Brand Proposal Strategy",
    "PTA":  "Payment-Term Arbitrage Strategy",
    "SPS":  "Supplier Performance Segmentation",
}


# ── Request / Response models ─────────────────────────────────
class SupplierSearchRequest(BaseModel):
    keywords:         str
    product_category: Optional[str]       = None
    brand:            Optional[str]       = None
    country:          Optional[str]       = None
    channel_codes:    Optional[List[str]] = []
    top_n:            Optional[int]       = 15


class SupplierResult(BaseModel):
    supplier_id:             str
    supplier_name:           str
    country:                 Optional[str]
    city:                    Optional[str]
    contact_email:           Optional[str]
    phone:                   Optional[str]
    website:                 Optional[str]
    product_categories:      Optional[str]
    products_brands_handled: Optional[str]
    brands:                  Optional[str]
    supplier_type:           Optional[str]
    source_type:             Optional[str]
    preferred:               Optional[bool]
    status:                  Optional[str]
    score:                   int
    match_reasons:           List[str]


class SupplierSearchResponse(BaseModel):
    success:       bool
    total_found:   int
    query_summary: str
    results:       List[SupplierResult]


# ── Scoring function (Suppliers_Clean_Phase1) ─────────────────
def score_vendor(row: dict, req: SupplierSearchRequest) -> tuple[int, list]:
    score   = 0
    reasons = []
    kw      = req.keywords.lower()
    words   = [w for w in kw.split() if len(w) >= 3] or kw.split()

    prod_cat = (row.get("product_categories")      or "").lower()
    prod_brd = (row.get("products_brands_handled")  or "").lower()
    brands   = (row.get("brands")                  or "").lower()
    sup_name = (row.get("supplier_name")            or "").lower()
    sup_type = (row.get("supplier_type")            or "").lower()

    for word in words[:6]:
        if len(word) < 4:   # skip short/common words
            continue
        if word in prod_cat:
            score += 3
            if "product_categories" not in reasons:
                reasons.append("product_categories")
        if word in prod_brd:
            score += 3
            if "products_brands_handled" not in reasons:
                reasons.append("products_brands_handled")
        if brands and word in brands:
            score += 2
            if "brands" not in reasons:
                reasons.append("brands")
        if word in sup_name:
            score += 1
            if "supplier_name" not in reasons:
                reasons.append("supplier_name")

    if req.brand and req.brand.lower() in prod_brd:
        score += 3
        if "brands (exact)" not in reasons:
            reasons.append("brands (exact)")

    if req.product_category and req.product_category.lower() in prod_cat:
        score += 2
        if "product_categories" not in reasons:
            reasons.append("product_categories")

    if req.channel_codes and "unclassified" not in sup_type:
        selected_channels = [CHANNEL_MAP.get(c, "").lower() for c in req.channel_codes]
        if any(ch in sup_type for ch in selected_channels if ch):
            score += 2
            reasons.append("channel match")

    if req.country and req.country.lower() == (row.get("country") or "").lower():
        score += 1
        reasons.append("country")

    if row.get("preferred"):
        score += 2
        reasons.append("preferred vendor")

    return score, reasons


# ── vendors_master search ─────────────────────────────────────
def _search_vendors_master(req: SupplierSearchRequest, db) -> List[SupplierResult]:
    """
    Searches vendors_master by keyword overlap against:
    vendor_name, brands, sourcing_rationale, description, channel_codes.

    sourcing_rationale is where the product context is stored at import time,
    e.g. "Horizontal Centrifugal Multistage Pump FW" — this is what makes
    imported vendor lists discoverable on similar future inquiries.

    Returns SupplierResult list sorted by verification_confidence desc.
    """
    cursor = db.cursor()
    try:
        words = [w for w in req.keywords.split() if len(w) >= 3][:6]
        if not words:
            words = req.keywords.split()[:3]
        if not words:
            return []

        # Build OR conditions — match any keyword word across all text fields
        conditions = []
        params     = []
        for word in words:
            w = f"%{word.lower()}%"
            conditions.append("""(
                LOWER(vendor_name)                     ILIKE %s OR
                LOWER(COALESCE(brands,''))              ILIKE %s OR
                LOWER(COALESCE(sourcing_rationale,''))  ILIKE %s OR
                LOWER(COALESCE(description,''))         ILIKE %s OR
                LOWER(COALESCE(channel_codes,''))       ILIKE %s
            )""")
            params.extend([w, w, w, w, w])

        where = "WHERE (" + " OR ".join(conditions) + ")"

        if req.brand:
            where  += " AND LOWER(COALESCE(brands,'')) ILIKE %s"
            params.append(f"%{req.brand.lower()}%")

        if req.country:
            where  += " AND LOWER(COALESCE(country,'')) ILIKE %s"
            params.append(f"%{req.country.lower()}%")

        cursor.execute(f"""
            SELECT
                vendor_name, country, city, email, phone, website,
                brands, sourcing_rationale, description, channel_codes,
                verification_confidence, source,
                is_preferred, preferred_divisions, preferred_categories
            FROM vendors_master
            {where}
            ORDER BY is_preferred DESC NULLS LAST, verification_confidence DESC, updated_at DESC
            LIMIT %s
        """, params + [req.top_n * 3])  # fetch extra for scoring

        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]

        # Score by keyword overlap — require ≥2 meaningful hits to avoid false matches
        desc_words = [w.lower() for w in req.keywords.split() if len(w) >= 4]
        scored     = []
        for row in rows:
            # Weight product-specific fields more heavily than company name
            prod_text = " ".join([
                row.get("sourcing_rationale", "") or "",
                row.get("description",        "") or "",
                row.get("brands",             "") or "",
            ]).lower()
            name_text = (row.get("vendor_name", "") or "").lower()
            full_text  = prod_text + " " + name_text

            prod_hits = sum(1 for w in desc_words if w in prod_text)
            name_hits = sum(1 for w in desc_words if w in name_text)
            kw_hits   = prod_hits * 2 + name_hits  # product fields weighted 2x

            # Require at least 2 meaningful product keyword hits
            if prod_hits < 1 and kw_hits < 3:
                continue

            conf  = float(row.get("verification_confidence") or 0.5)
            score = kw_hits * 3 + conf * 5
            # Preferred vendors get a significant boost so they always surface first
            if row.get("is_preferred"):
                score += 10
            scored.append({**row, "_score": score, "_kw_hits": kw_hits})

        scored.sort(key=lambda x: x["_score"], reverse=True)

        results = []
        for r in scored[:req.top_n]:
            conf     = float(r.get("verification_confidence") or 0.5)
            kw_hits  = r.get("_kw_hits", 0)
            reasons  = [f"verified DB ({kw_hits} keyword hits)"]
            if r.get("is_preferred"):
                reasons.insert(0, "preferred supplier")
            if conf >= 0.9:
                reasons.append("high confidence")
            results.append(SupplierResult(
                supplier_id             = f"master-{r.get('vendor_name','')}",
                supplier_name           = r.get("vendor_name", ""),
                country                 = r.get("country"),
                city                    = r.get("city"),
                contact_email           = r.get("email"),
                phone                   = r.get("phone"),
                website                 = r.get("website"),
                product_categories      = r.get("sourcing_rationale"),
                products_brands_handled = r.get("brands"),
                brands                  = r.get("brands"),
                supplier_type           = r.get("channel_codes"),
                source_type             = r.get("source"),
                preferred               = bool(r.get("is_preferred")) or conf >= 0.9,
                status                  = "active",
                score                   = min(10, round(r["_score"])),
                match_reasons           = reasons,
            ))

        return results

    except Exception as e:
        print(f"  ⚠️  vendors_master search failed: {e}")
        return []
    finally:
        cursor.close()


# ── Main search endpoint ──────────────────────────────────────
@router.post("/search", response_model=SupplierSearchResponse)
def search_suppliers(req: SupplierSearchRequest, db=Depends(get_suppliers_db)):
    cursor = db.cursor()
    try:
        # ── Source 1: vendors_master (verified, imported + AI-discovered) ──
        master_results = _search_vendors_master(req, db)

        # ── Source 2: Suppliers_Clean_Phase1 (legacy archive) ─────────────
        conditions = ['LOWER("Status") = \'active\'']
        params     = []

        if req.keywords:
            kw_conditions = []
            words = [w for w in req.keywords.split() if len(w) >= 3]
            if not words:
                words = req.keywords.split()
            for word in words[:6]:
                w = f"%{word.lower()}%"
                kw_conditions.append(
                    '(LOWER("Product Categories") ILIKE %s '
                    'OR LOWER("Products / Brands Handled") ILIKE %s '
                    'OR LOWER("Brands") ILIKE %s '
                    'OR LOWER("Supplier Name") ILIKE %s)'
                )
                params.extend([w, w, w, w])
            if kw_conditions:
                conditions.append(f"({' OR '.join(kw_conditions)})")

        if req.brand:
            conditions.append(
                '(LOWER("Brands") ILIKE %s OR LOWER("Products / Brands Handled") ILIKE %s)'
            )
            b = f"%{req.brand.lower()}%"
            params.extend([b, b])

        if req.country:
            conditions.append('LOWER("Country") ILIKE %s')
            params.append(f"%{req.country.lower()}%")

        if req.channel_codes:
            ch_conditions = []
            for code in req.channel_codes:
                ch_name = CHANNEL_MAP.get(code, "")
                if ch_name:
                    ch_conditions.append('LOWER("Supplier Type (Group A Channel)") ILIKE %s')
                    params.append(f"%{ch_name.lower()}%")
            ch_conditions.append('"Supplier Type (Group A Channel)" ILIKE %s')
            params.append('%Unclassified%')
            if ch_conditions:
                conditions.append(f"({' OR '.join(ch_conditions)})")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        sql = f"""
            SELECT
                "Supplier ID"                     AS supplier_id,
                "Supplier Name"                   AS supplier_name,
                "Country"                         AS country,
                "City"                            AS city,
                "Contact Email"                   AS contact_email,
                "Phone"                           AS phone,
                "Website"                         AS website,
                "Product Categories"              AS product_categories,
                "Products / Brands Handled"       AS products_brands_handled,
                "Brands"                          AS brands,
                "Supplier Type (Group A Channel)" AS supplier_type,
                "Source Type (Group B Strategy)"  AS source_type,
                "Preferred?"                      AS preferred,
                "Status"                          AS status
            FROM "Suppliers_Clean_Phase1"
            {where}
            LIMIT 200
        """

        cursor.execute(sql, params)
        columns   = [desc[0] for desc in cursor.description]
        rows      = [dict(zip(columns, row)) for row in cursor.fetchall()]

        legacy_results = []
        if rows:
            scored = []
            for row in rows:
                score, reasons = score_vendor(row, req)
                # Require minimum score of 6 (at least 2 meaningful product keyword hits)
                if score >= 6:
                    scored.append({**row, "score": score, "match_reasons": reasons})
            scored.sort(key=lambda x: x["score"], reverse=True)
            for r in scored[:req.top_n]:
                legacy_results.append(SupplierResult(
                    supplier_id             = r.get("supplier_id") or "",
                    supplier_name           = r.get("supplier_name") or "",
                    country                 = r.get("country"),
                    city                    = r.get("city"),
                    contact_email           = r.get("contact_email"),
                    phone                   = str(r.get("phone")) if r.get("phone") else None,
                    website                 = r.get("website"),
                    product_categories      = r.get("product_categories"),
                    products_brands_handled = r.get("products_brands_handled"),
                    brands                  = r.get("brands"),
                    supplier_type           = r.get("supplier_type"),
                    source_type             = r.get("source_type"),
                    preferred               = r.get("preferred"),
                    status                  = r.get("status"),
                    score                   = min(10, r["score"]),
                    match_reasons           = r["match_reasons"],
                ))

        # ── Merge: master first (verified), legacy as supplement ──────────
        # Deduplicate by normalized vendor name
        import re as _re

        def _norm(name: str) -> str:
            n = name.lower().strip()
            for suffix in [r"\bllc\b", r"\bltd\b", r"\binc\b", r"\bco\b",
                            r"\bfze\b", r"\bfzc\b", r"\bsaog\b"]:
                n = _re.sub(suffix, "", n)
            return _re.sub(r"[^\w\s]", "", n).strip()

        seen     = set()
        combined = []

        for r in master_results:
            norm = _norm(r.supplier_name)
            if norm not in seen:
                seen.add(norm)
                combined.append(r)

        for r in legacy_results:
            norm = _norm(r.supplier_name)
            if norm not in seen:
                seen.add(norm)
                combined.append(r)

        # Cap at top_n
        combined      = combined[:req.top_n]
        master_count  = sum(1 for r in combined
                            if str(r.supplier_id).startswith("master-"))
        legacy_count  = len(combined) - master_count

        query_summary = (
            f"Found {len(combined)} vendors for '{req.keywords}'"
            + (f" ({master_count} verified" +
               (f", {legacy_count} legacy" if legacy_count else "") + ")"
               if master_count else "")
            + (f" | Brand: {req.brand}"              if req.brand          else "")
            + (f" | Country: {req.country}"           if req.country        else "")
            + (f" | Channels: {', '.join(req.channel_codes)}"
               if req.channel_codes else "")
        )

        return SupplierSearchResponse(
            success=True,
            total_found=len(combined),
            query_summary=query_summary,
            results=combined,
        )

    except Exception as e:
        print(f"❌ SUPPLIER SEARCH ERROR: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


# ── GET: preferred vendors pre-check ─────────────────────────
@router.get("/preferred")
def get_preferred_vendors(
    division: Optional[str] = None,
    category: Optional[str] = None,
    db=Depends(get_suppliers_db),
):
    """Return all preferred vendors, optionally filtered by division or category."""
    cursor = db.cursor()
    try:
        conditions = ["is_preferred = TRUE"]
        params = []
        if division:
            conditions.append("(preferred_divisions IS NULL OR preferred_divisions ILIKE %s)")
            params.append(f"%{division}%")
        if category:
            conditions.append("(preferred_categories IS NULL OR preferred_categories ILIKE %s)")
            params.append(f"%{category}%")
        where = "WHERE " + " AND ".join(conditions)
        cursor.execute(f"""
            SELECT id, vendor_name, country, city, email, phone, website,
                   brands, channel_codes, sourcing_rationale,
                   preferred_divisions, preferred_categories,
                   verification_confidence, preferred_marked_at
            FROM vendors_master
            {where}
            ORDER BY vendor_name ASC
        """, params)
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        return {"success": True, "preferred_vendors": rows, "total": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


# ── PATCH: update email for a DB supplier ─────────────────────
class UpdateEmailRequest(BaseModel):
    supplier_id: str   # "master-<name>" or legacy Supplier ID
    email:       str


@router.patch("/update-email")
def update_supplier_email(req: UpdateEmailRequest, db=Depends(get_suppliers_db)):
    """
    Persist an email edit made in the Procurement Agent UI back to the database.
    Handles both vendors_master (supplier_id starts with 'master-') and
    Suppliers_Clean_Phase1 (legacy numeric/string IDs).
    """
    cursor = db.cursor()
    try:
        email = req.email.strip()
        sid   = req.supplier_id.strip()

        if sid.startswith("master-"):
            # vendors_master — keyed by vendor_name
            name = sid[len("master-"):]
            cursor.execute(
                'UPDATE vendors_master SET email = %s, updated_at = NOW() WHERE vendor_name = %s',
                (email, name),
            )
            updated = cursor.rowcount
        else:
            # Suppliers_Clean_Phase1 — keyed by "Supplier ID" column
            cursor.execute(
                'UPDATE "Suppliers_Clean_Phase1" SET "Contact Email" = %s WHERE "Supplier ID" = %s',
                (email, sid),
            )
            updated = cursor.rowcount

        db.commit()
        if updated == 0:
            raise HTTPException(status_code=404, detail=f"Supplier '{sid}' not found in database")
        print(f"  ✅ Email updated for supplier '{sid}' → {email}")
        return {"success": True, "updated": updated}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ UPDATE EMAIL ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()