"""
routes/vendor_discovery.py

Agent 2 — Supplier Intelligence

Pipeline:
  0. Inquiry validation
  0b. Manufacturer/brand extraction (Fix 1)
  1. Sourcing (30) + ranking (15) in parallel
  2. Merge with consensus scoring
  3. Quality evaluation
  4. Deep discovery (conditional)
  5. Claude validation (conditional)
  6. Relevance filter + contact enrichment
     → Batch reality check built in
     → Retry 1: Deep discovery stricter
     → Retry 2: Sonar direct discovery
  7. Target 15: top-up rounds if below target
     → Round A: Sonar direct
     → Round B: AI sourcing pass
  8. Final cleanup

Fixes in this version:
  Fix 1: Manufacturer detection — bypasses batch check
  Fix 2: B2C blocklist in sonar_discovery.py
  Fix 3: used_replacements set now threaded through _topup_enrich
         so the same alternative is never used twice across the
         entire session (main run + all top-up rounds)
"""

import os
import re
import json
from fastapi          import APIRouter, HTTPException, Depends
from pydantic         import BaseModel
from typing           import List, Dict, Optional, Set

from services.web_search_discovery import (
    openai_claude_discover_vendors,
    groq_discover_vendors,
    groq_relevance_filter,
    extract_country_from_delivery,
)
from services.contact_enrichment import (
    enrich_vendor_contacts,
    deduplicate_vendors,
    _normalize_company_name,
)
from services.sonar_discovery import is_b2c_vendor
from database import get_db

router = APIRouter(tags=["Vendor Discovery"])


# ── Permanent company blacklist endpoints ──────────────────────

class BlacklistEntry(BaseModel):
    company_name: str
    reason: Optional[str] = ""

@router.get("/discovery/blacklist")
def get_blacklist(db=Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT id, company_name, reason, created_at FROM discovery_blacklist ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return {"success": True, "blacklist": [
            {"id": r[0], "company_name": r[1], "reason": r[2], "created_at": r[3].isoformat() if r[3] else None}
            for r in rows
        ]}
    finally:
        cursor.close()

@router.post("/discovery/blacklist")
def add_to_blacklist(entry: BlacklistEntry, db=Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO discovery_blacklist (company_name, reason) VALUES (%s, %s) ON CONFLICT (company_name) DO NOTHING RETURNING id",
            (entry.company_name.strip(), entry.reason or "")
        )
        row = cursor.fetchone()
        db.commit()
        return {"success": True, "already_existed": row is None}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.delete("/discovery/blacklist/clear-all")
def clear_all_blacklist(db=Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM discovery_blacklist")
        count = cursor.rowcount
        db.commit()
        return {"success": True, "deleted": count}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/discovery/blacklist/{entry_id}")
def remove_from_blacklist(entry_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM discovery_blacklist WHERE id = %s RETURNING id", (entry_id,))
        row = cursor.fetchone()
        db.commit()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

TARGET_VENDOR_COUNT   = 20   # AI new suppliers shown per run
DB_SUPPLIER_TARGET    = 10   # DB (prompt) suppliers fetched

# ── Live progress store ────────────────────────────────────────
# Keyed by search_id.
# Each value: {"log": [str, ...], "vendors": [...], "ts": float}
_enrichment_progress: Dict[str, dict] = {}
_PROGRESS_TTL = 900  # 15 minutes — auto-clean stale entries to prevent memory leak

def _clean_stale_progress():
    import time
    cutoff = time.time() - _PROGRESS_TTL
    stale = [k for k, v in _enrichment_progress.items() if v.get("ts", 0) < cutoff]
    for k in stale:
        del _enrichment_progress[k]
    if stale:
        print(f"  🧹 Cleaned {len(stale)} stale progress entries")

def _plog(search_id: Optional[str], msg: str):
    """Append a log line and print it to terminal."""
    print(msg)
    if search_id and search_id in _enrichment_progress:
        log = _enrichment_progress[search_id]["log"]
        if len(log) < 150:   # B1: cap at 150 lines — ~15KB max per search
            log.append(msg)

@router.get("/vendors/discovery-progress/{search_id}")
def get_discovery_progress(search_id: str):
    _clean_stale_progress()
    data = _enrichment_progress.get(search_id, {})
    return {"log": data.get("log", []), "vendors": data.get("vendors", [])}


# ── Request model ─────────────────────────────────────────────

class DiscoverVendorsRequest(BaseModel):
    part_number:         Optional[str]  = None
    description:         str
    quantity:            Optional[str]  = None
    delivery:            Optional[str]  = None
    specs:               Optional[str]  = None
    brand:               Optional[str]  = None
    channel_codes:       List[str]      = []
    channel_labels:      List[str]      = []   # e.g. ["LAD: Local Authorized Distributors", ...]
    existing_vendors:    List[str]      = []
    existing_websites:   List[str]      = []   # websites already shown — exclude their domains
    blacklisted_vendors: List[str]      = []   # user explicitly deselected — NEVER suggest again
    extra_instructions:  Optional[str]  = None
    target_count:        Optional[int]  = None  # user-specified target; falls back to TARGET_VENDOR_COUNT
    search_id:           Optional[str]  = None  # for live progress tracking


# ── Inquiry validation ────────────────────────────────────────

REFERENCE_CODE_PATTERNS = [
    r"^\d+\.\d+(\.\d+)*(,\s*\d+\.\d+(\.\d+)*)*$",
    r"^[A-Z]{1,5}-?\d{3,8}$",
    r"^(item|ref|no|section|clause|para)[\s\.\-]\d",
    r"^\d{1,4}[a-z]?$",
]


def _validate_description(description: str) -> Optional[Dict]:
    desc  = description.strip()
    words = [w for w in desc.split() if len(w) > 1]

    if len(desc) < 10:
        return {"error": "description_too_short",
                "message": f"'{desc}' is too short. Please provide a full product name."}
    if len(words) < 2:
        return {"error": "description_too_vague",
                "message": f"'{desc}' appears to be a reference code. Please provide the actual product description."}
    for pattern in REFERENCE_CODE_PATTERNS:
        if re.match(pattern, desc, re.IGNORECASE):
            return {
                "error":   "reference_code_detected",
                "message": (
                    f"'{desc}' looks like a document reference number. "
                    f"Please paste the actual item description from the drawing or BOQ "
                    f"(e.g. 'Structural Steel Sections EN 10025 Grade S355 JR' "
                    f"instead of '5.1.1, 5.1.2')."
                ),
            }
    if re.match(r"^[\d\s,.\-/\\()]+$", desc):
        return {"error": "no_text_content",
                "message": f"'{desc}' contains only numbers and symbols. Please provide the actual product name."}
    return None


# ── Manufacturer extraction ───────────────────────────────────

KNOWN_BRANDS = {
    "ingersoll rand", "ingersoll-rand", "abb", "siemens", "schneider",
    "honeywell", "emerson", "parker", "danfoss", "grundfos", "yokogawa",
    "flowserve", "spirax", "endress", "hauser", "atlas copco", "sandvik",
    "kennametal", "seco", "iscar", "mitsubishi", "fanuc", "bosch",
    "dewalt", "makita", "hilti", "stanley", "snap-on", "snap on",
    "caterpillar", "cummins", "perkins", "kohler", "briggs", "stratton",
    "3m", "henkel", "loctite", "dow", "dupont", "basf",
}


def _extract_manufacturer_vendors(
    description: str,
    part_number: Optional[str],
    brand:       Optional[str],
    delivery:    Optional[str],
) -> List[Dict]:
    found_brands = set()
    text = f"{description} {part_number or ''} {brand or ''}".lower()
    for known_brand in KNOWN_BRANDS:
        if known_brand in text:
            found_brands.add(known_brand)
    if not found_brands:
        return []

    from services.web_search_discovery import extract_country_from_delivery as _ecd
    country = _ecd(delivery or "UAE")
    vendors = []
    for brand_name in found_brands:
        display = brand_name.title()
        vendors.append({
            "name":               display,
            "country":            "Global",
            "city":               "",
            "email":              "",
            "phone":              "",
            "website":            "",
            "brands":             display,
            "channel_code":       "OEM",
            "confidence_score":   10.0,
            "sourcing_rationale": "OEM manufacturer of this product — direct source",
            "description":        f"Original equipment manufacturer. Contact their regional office or authorized distributor in {country}.",
            "source":             "manufacturer_direct",
        })
        vendors.append({
            "name":               f"{display} {country} / Authorized Distributor",
            "country":            country,
            "city":               "Dubai",
            "email":              "",
            "phone":              "",
            "website":            "",
            "brands":             display,
            "channel_code":       "LAD",
            "confidence_score":   9.5,
            "sourcing_rationale": f"Authorized distributor or regional office for {display} in {country}",
            "description":        f"Regional authorized distributor for {display} products.",
            "source":             "manufacturer_direct",
        })

    if vendors:
        print(f"  🏭 Manufacturer detected: {[b.title() for b in found_brands]} — added {len(vendors)} entries")
    return vendors


# ── Sourcing agents ───────────────────────────────────────────

def run_openai_sourcing(
    description:      str,
    part_number:      Optional[str],
    brand:            Optional[str],
    channel_codes:    List[str],
    existing_vendors: List[str],
    delivery:         Optional[str],
    extra:            Optional[str],
    target_count:     int = 30,
) -> List[Dict]:
    from services.openai_fallback import _call_openai
    channels_str = ", ".join(channel_codes) if channel_codes else "LAD, OEM, IGS, OCD, ISD, B2B"
    exclude_str  = "\n".join(f"- {v}" for v in existing_vendors[:40]) if existing_vendors else "None"

    country_str   = extract_country_from_delivery(delivery or "UAE")
    country_list  = [c.strip() for c in country_str.split(",") if c.strip()] or ["UAE"]
    countries_str = ", ".join(country_list)
    per_country   = max(3, target_count // len(country_list))
    country_quotas = "\n".join(f"- {c}: at least {per_country} suppliers" for c in country_list)
    prompt_block  = f"\nSPECIAL INSTRUCTIONS (MUST FOLLOW):\n{extra}" if extra else ""

    prompt = f"""You are a senior procurement sourcing specialist for an industrial trading company in Dubai, UAE.

ITEM TO SOURCE:
- Description: {description}
- Part Number: {part_number or 'N/A'}
- Brand: {brand or 'Unknown'}
- Delivery countries: {countries_str}
{prompt_block}
SOURCING CHANNELS: {channels_str}

ALREADY FOUND — DO NOT REPEAT:
{exclude_str}

COUNTRY DISTRIBUTION — spread results across ALL requested countries:
{country_quotas}

RULES:
- Return suppliers from EVERY country listed above — do NOT only return UAE/Dubai
- Only include real B2B industrial suppliers, authorized distributors, specialist traders
- Do NOT include B2C marketplaces (Amazon, Noon, Alibaba, Souq, etc.)
- Each company must have a UNIQUE, REAL website domain — no two entries from the same parent group or holding company
- DIVERSITY is critical: avoid clustering results from the same industrial district or group (e.g. do not return 3 subsidiaries of the same holding)
- Prefer companies with a clear web presence and known contact email
- Do NOT repeat any company already listed in ALREADY FOUND above, including subsidiaries or sister companies of those
- If SPECIAL INSTRUCTIONS are given above, follow them strictly

Find {target_count} NEW real supplier companies with DIVERSE ownership and unique domains. MUST include suppliers from each: {countries_str}.
DO NOT include email, phone, or website — these will be verified separately.

Return ONLY a valid JSON array. No markdown:
[{{
  "name": "Full Company Name",
  "country": "Saudi Arabia",
  "city": "Riyadh",
  "email": "",
  "phone": "",
  "website": "",
  "brands": "specific brands they handle",
  "channel_code": "LAD",
  "confidence_score": 8.5,
  "sourcing_rationale": "specific reason this company would supply this exact item",
  "description": "what this company does and why relevant",
  "source": "openai_sourcing"
}}]"""

    # GPT-4o-mini first → Claude Haiku → Groq last resort
    raw = None
    try:
        raw = _call_openai(prompt, model="gpt-4o-mini", max_tokens=1000)
        print("  ✅ Sourcing: GPT succeeded")
    except Exception as e:
        print(f"  ⚠️  GPT sourcing failed: {e} — trying Claude Haiku")
        try:
            from services.llm_router import ask_llm
            raw = ask_llm(prompt, json_mode=False, max_tokens=1000, start_from="anthropic-haiku")
            print("  ✅ Sourcing: Claude Haiku succeeded")
        except Exception as e2:
            print(f"  ⚠️  Claude also failed: {e2} — trying Groq")
            try:
                from services.groq_client import ask_groq
                raw = ask_groq(prompt, json_mode=False, max_tokens=1000)
                print("  ✅ Sourcing: Groq succeeded")
            except Exception as e3:
                print(f"  ⚠️  All LLMs failed for sourcing: {e3}")
    if not raw:
        return []
    try:
        clean = re.sub(r"```json|```", "", raw).strip()
        try:
            result = json.loads(clean)
        except json.JSONDecodeError:
            last   = clean.rfind('},')
            result = json.loads(clean[:last+1] + ']') if last > 0 else []
        vendors = [v for v in (result if isinstance(result, list) else [])
                   if not is_b2c_vendor(v)]
        print(f"  ✅ Sourcing found {len(vendors)} vendors")
        return vendors
    except Exception as e:
        print(f"  ⚠️  Sourcing parse error: {e}")
        return []


def run_openai_ranking(
    description:      str,
    part_number:      Optional[str],
    brand:            Optional[str],
    channel_codes:    List[str],
    existing_vendors: List[str],
    delivery:         Optional[str],
    extra:            Optional[str],
    target_count:     int = 15,
) -> List[Dict]:
    from services.openai_fallback import _call_openai
    channels_str = ", ".join(channel_codes) if channel_codes else "LAD, OEM, IGS, OCD, ISD, B2B"
    exclude_str  = "\n".join(f"- {v}" for v in existing_vendors[:40]) if existing_vendors else "None"

    country_str   = extract_country_from_delivery(delivery or "UAE")
    country_list  = [c.strip() for c in country_str.split(",") if c.strip()] or ["UAE"]
    countries_str = ", ".join(country_list)
    per_country   = max(2, target_count // len(country_list))
    country_quotas = "\n".join(f"- {c}: at least {per_country} suppliers" for c in country_list)
    prompt_block  = f"\nSPECIAL INSTRUCTIONS (MUST FOLLOW):\n{extra}" if extra else ""

    prompt = f"""You are a principal procurement analyst with 15+ years experience in UAE/GCC industrial supply chains.

Identify the MOST RELEVANT and HIGHEST CONFIDENCE B2B suppliers for this item.
Only include companies you are highly confident actually supply this product.
Do NOT include B2C marketplaces (Amazon, Noon, Alibaba, Souq etc.)

ITEM:
- Description: {description}
- Part Number: {part_number or 'N/A'}
- Brand: {brand or 'Unknown'}
- Delivery countries: {countries_str}
{prompt_block}
CHANNELS: {channels_str}

ALREADY FOUND — DO NOT REPEAT:
{exclude_str}

COUNTRY DISTRIBUTION:
{country_quotas}

SCORING GUIDE:
- 9-10: OEM manufacturer or verified authorized distributor
- 7-8: Well-known regional distributor with clear product match
- 5-6: General industrial supplier likely to stock this
- Below 5: Do not include

Find {target_count} HIGH-CONFIDENCE B2B suppliers from ALL these countries: {countries_str}.
DO NOT include email, phone, or website — verified separately.

Return ONLY a valid JSON array. No markdown:
[{{
  "name": "Full Company Name",
  "country": "UAE",
  "city": "Dubai",
  "email": "",
  "phone": "",
  "website": "",
  "brands": "specific brands they handle",
  "channel_code": "OEM",
  "confidence_score": 9.0,
  "sourcing_rationale": "specific reason this company would supply this exact item",
  "description": "detailed description of company specialization",
  "source": "openai_ranking"
}}]"""

    # GPT-4o-mini first → Claude Haiku → Groq last resort
    raw = None
    try:
        raw = _call_openai(prompt, model="gpt-4o-mini", max_tokens=1000)
        print("  ✅ Ranking: GPT succeeded")
    except Exception as e:
        print(f"  ⚠️  GPT ranking failed: {e} — trying Claude Haiku")
        try:
            from services.llm_router import ask_llm
            raw = ask_llm(prompt, json_mode=False, max_tokens=1000, start_from="anthropic-haiku")
            print("  ✅ Ranking: Claude Haiku succeeded")
        except Exception as e2:
            print(f"  ⚠️  Claude also failed: {e2} — trying Groq")
            try:
                from services.groq_client import ask_groq
                raw = ask_groq(prompt, json_mode=False, max_tokens=1000)
                print("  ✅ Ranking: Groq succeeded")
            except Exception as e3:
                print(f"  ⚠️  All LLMs failed for ranking: {e3}")
    if not raw:
        return []
    try:
        clean = re.sub(r"```json|```", "", raw).strip()
        try:
            result = json.loads(clean)
        except json.JSONDecodeError:
            last   = clean.rfind('},')
            result = json.loads(clean[:last+1] + ']') if last > 0 else []
        vendors = [v for v in (result if isinstance(result, list) else [])
                   if not is_b2c_vendor(v)]
        print(f"  ✅ Ranking found {len(vendors)} vendors")
        return vendors
    except Exception as e:
        print(f"  ⚠️  Ranking parse error: {e}")
        return []


def merge_groq_results(sourcing: List[Dict], ranking: List[Dict]) -> List[Dict]:
    sourcing_names = {v.get("name","").lower().strip(): v for v in sourcing}
    ranking_names  = {v.get("name","").lower().strip(): v for v in ranking}
    merged         = {}
    for name_key, v in sourcing_names.items():
        merged[name_key] = dict(v)
    for name_key, v in ranking_names.items():
        if name_key in merged:
            existing = merged[name_key]
            existing["source"] = "consensus"
            existing["confidence_score"] = min(1.0, (
                (existing.get("confidence_score") or 0.5) +
                (v.get("confidence_score") or 0.5)
            ) / 2 + 0.1)
        else:
            merged[name_key] = dict(v)
    result = list(merged.values())
    result.sort(key=lambda x: x.get("confidence_score") or 0, reverse=True)
    return result


# ── Helpers ───────────────────────────────────────────────────

def _verified_count(vendors: List[Dict]) -> int:
    return sum(1 for v in vendors if v.get("verified") or v.get("manual_lookup"))


def _add_rfq_scores(vendors: List[Dict], description: str, country: str) -> List[Dict]:
    """
    Uses Claude Haiku to assign each vendor:
      - priority_rank (1 = highest — most likely to respond fast with a quotation)
      - rfq_response_probability (% likelihood of response in 3–5 business days)
      - quotation_speed_rating (Very High / High / Medium / Low)

    Scoring criteria (from user's prompt):
      - Direct manufacturer presence → highest
      - Authorized distributor with local inventory → high
      - Industrial/Oil & Gas supply experience → bonus
      - Multiple contact channels → bonus
      - Generic trader with no product specialization → low
    """
    if not vendors:
        return vendors

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        # Fallback: assign basic scores from confidence_score
        for i, v in enumerate(vendors):
            ch = v.get("channel_code", "").upper()
            base_prob = 85 if ch == "OEM" else 75 if ch == "LAD" else 60
            v["priority_rank"]             = i + 1
            v["rfq_response_probability"]  = max(40, base_prob - i * 3)
            v["quotation_speed_rating"]    = "High" if base_prob >= 75 else "Medium"
        return vendors

    rows = [
        {
            "i":         i,
            "name":      v.get("name", ""),
            "channel":   v.get("channel_code", ""),
            "brands":    v.get("brands", ""),
            "rationale": v.get("sourcing_rationale", "")[:80],
            "mismatch":  v.get("product_mismatch", False),
        }
        for i, v in enumerate(vendors)
    ]

    prompt = f"""You are a procurement specialist. Rank these vendors by how likely they are to respond quickly with a quotation for:
{description[:100]} | Country: {country}

Priority criteria:
- Direct OEM manufacturer = highest priority
- Authorized distributor with local inventory = high
- Industrial/Oil & Gas supply experience = bonus
- Multiple contact channels = bonus
- Generic trader or product_mismatch=True = low priority

VENDORS:
{json.dumps(rows)}

Assign each vendor:
- priority_rank: 1 (best) to {len(vendors)} (worst)
- rfq_response_probability: integer % (40-95) — chance of reply within 3-5 business days
- quotation_speed_rating: "Very High" / "High" / "Medium" / "Low"

Return JSON array only:
[{{"i":0,"rank":1,"prob":90,"speed":"Very High"}}]"""

    # Groq → GPT → Claude
    raw = None
    try:
        from services.groq_client import ask_groq
        raw = ask_groq(prompt, json_mode=False, max_tokens=500)
        print("  ✅ RFQ scoring: Groq succeeded")
    except Exception as e:
        print(f"  ⚠️  Groq RFQ scoring failed: {e} — trying GPT")
        try:
            from services.openai_fallback import _call_openai
            raw = _call_openai(prompt, model="gpt-4o-mini", max_tokens=500)
            print("  ✅ RFQ scoring: GPT succeeded")
        except Exception as e2:
            print(f"  ⚠️  GPT failed: {e2} — trying Claude Haiku")
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                resp   = client.messages.create(
                    model="claude-haiku-4-5-20251001", max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.content[0].text.strip()
                print("  ✅ RFQ scoring: Claude Haiku succeeded")
            except Exception as e3:
                print(f"  ⚠️  RFQ scoring all LLMs failed: {e3} — using default order")

    if raw:
        try:
            clean     = re.sub(r"```json|```", "", raw).strip()
            scores    = json.loads(clean)
            score_map = {e["i"]: e for e in scores if "i" in e}
            for i, v in enumerate(vendors):
                entry = score_map.get(i, {})
                v["priority_rank"]            = entry.get("rank", i + 1)
                v["rfq_response_probability"] = entry.get("prob", 60)
                v["quotation_speed_rating"]   = entry.get("speed", "Medium")
            vendors.sort(key=lambda x: x.get("priority_rank", 99))
            print(f"  ✅ RFQ scoring done — {len(vendors)} vendors ranked")
        except Exception as e:
            print(f"  ⚠️  RFQ scoring parse error: {e} — using default order")

    for i, v in enumerate(vendors):
        if "priority_rank" not in v:
            v["priority_rank"]            = i + 1
            v["rfq_response_probability"] = 60
            v["quotation_speed_rating"]   = "Medium"

    return vendors


# ── Main discovery endpoint ───────────────────────────────────

@router.post("/vendors/discover")
def discover_vendors(req: DiscoverVendorsRequest):
    # Runs in FastAPI's threadpool so the event loop stays free for progress polls
    sid = req.search_id
    import time as _time
    _clean_stale_progress()
    _enrichment_progress[sid] = {"log": [], "vendors": [], "ts": _time.time()} if sid else None

    # Merge DB permanent blacklist into session blacklist
    try:
        from database import get_connection
        _bl_conn = get_connection()
        _bl_cur  = _bl_conn.cursor()
        _bl_cur.execute("SELECT company_name FROM discovery_blacklist")
        db_blacklisted = [r[0] for r in _bl_cur.fetchall()]
        _bl_cur.close()
        _bl_conn.close()
        req.blacklisted_vendors = list(set(list(req.blacklisted_vendors) + db_blacklisted))
    except Exception:
        pass

    _plog(sid, "=" * 50)
    _plog(sid, f"New Vendor Discovery: {req.part_number or req.description[:50]}")
    _plog(sid, f"Channels: {', '.join(req.channel_codes)}")
    if req.extra_instructions:
        _plog(sid, f"Refinement: {req.extra_instructions}")
    _plog(sid, "=" * 50)

    try:
        return _discover_vendors_inner(req, sid)
    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail={
            "error":   "discovery_pipeline_error",
            "message": f"Vendor discovery failed: {type(exc).__name__}: {str(exc)[:200]}",
            "hint":    "Check backend logs for full traceback.",
        })


def _clean_description(description: str) -> str:
    """
    Strip technical code prefixes from descriptions like:
    "VALVE,CHK;SWING,1",CL800,FNPT,CS,1 - CHECK VALVE, SWING TYPE, 1 INCH..."
    → "CHECK VALVE, SWING TYPE, 1 INCH..."

    If a long dash separator ' - ' exists and the human-readable part after it
    is at least 10 chars, use that. Otherwise return the original.
    """
    sep = " - "
    idx = description.find(sep)
    if idx != -1:
        human_part = description[idx + len(sep):].strip()
        if len(human_part) >= 10:
            return human_part
    return description


def _discover_vendors_inner(req: DiscoverVendorsRequest, sid: Optional[str] = None):
    # ── Step 0: Validate description ──────────────────────────
    validation_error = _validate_description(req.description)
    if validation_error:
        _plog(sid, f"  Validation failed: {validation_error['error']}")
        raise HTTPException(status_code=422, detail={
            **validation_error,
            "hint": "Please provide the actual product name, not a reference number.",
        })

    # ── Step 0b: Manufacturer extraction ─────────────────────
    clean_desc_early = _clean_description(req.description)
    manufacturer_vendors = _extract_manufacturer_vendors(
        clean_desc_early, req.part_number, req.brand, req.delivery
    )

    # ── Setup ──────────────────────────────────────────────────
    country_str        = extract_country_from_delivery(req.delivery or "UAE")
    country_list       = [c.strip() for c in country_str.split(",") if c.strip()] or ["UAE"]
    effective_target   = max(1, min(50, req.target_count or TARGET_VENDOR_COUNT))
    # When user specifies exact count, use it directly; otherwise add buffer for drop-off
    _buffer            = 0 if req.target_count else 8
    per_country_target = max(2, (effective_target + _buffer) // len(country_list))

    channel_labels = req.channel_labels or []
    channels_full  = ", ".join(channel_labels) if channel_labels else ", ".join(req.channel_codes)
    clean_desc = _clean_description(req.description)
    rich_description = clean_desc
    if req.specs and req.specs.strip():
        rich_description = f"{clean_desc}\nProduct specifications/notes: {req.specs.strip()}"
    extra_parts = []
    if req.specs and req.specs.strip():
        extra_parts.append(f"Document specifications/notes: {req.specs.strip()}")
    if req.extra_instructions and req.extra_instructions.strip():
        extra_parts.append(f"User instructions: {req.extra_instructions.strip()}")
    effective_extra = "\n".join(extra_parts) if extra_parts else None

    existing_lower    = {v.lower().strip() for v in req.existing_vendors}
    blacklisted_lower = {v.lower().strip() for v in req.blacklisted_vendors}
    def _norm_bl(name: str) -> str:
        import re as _re
        n = name.lower().strip()
        n = _re.sub(r"\b(llc|ltd|inc|corp|co|group|trading|fze|fzc|saog|saoc|wll|bsc|pvt|private|limited)\b", "", n)
        return _re.sub(r"[^\w\s]", "", n).strip()
    blacklisted_norm = {_norm_bl(v) for v in req.blacklisted_vendors}
    def _is_blacklisted(name: str) -> bool:
        nl = name.lower().strip()
        if nl in blacklisted_lower: return True
        if _norm_bl(nl) in blacklisted_norm: return True
        # Also check all_excluded (grows each round with DB blacklist refreshes)
        return nl in {n.lower().strip() for n in all_excluded}
    def _has_valid_email(v: Dict) -> bool:
        email = (v.get("email") or "").strip()
        if not email: return False
        parts = [e.strip() for e in email.split(",")]
        return any("@" in e and "." in e.split("@")[-1] for e in parts if e)

    # ── Single discovery pass ──
    accumulated:    List[Dict] = []
    seen_names:     Set[str]   = set()
    seen_websites:  Set[str]   = set()
    # Only exclude vendors already shown to the user (existing_vendors) — not the blacklist
    all_excluded       = list(req.existing_vendors)
    seen_websites_disc = list(req.existing_websites)
    # When user specifies an exact count (Find More), use it directly — no buffer
    round_target       = effective_target if req.target_count else min(40, effective_target + 15)

    if manufacturer_vendors:
        accumulated.extend(manufacturer_vendors)

    _round = 1
    if True:  # single pass
        still_needed = effective_target - len(accumulated)

        _plog(sid, f"[Step 1] Discovering vendors | target: {effective_target} | countries: {', '.join(country_list)}")

        _kw = dict(
            description       = rich_description,
            part_number       = req.part_number,
            brand             = req.brand,
            channel_codes     = req.channel_codes,
            channel_labels    = channels_full,
            existing_vendors  = all_excluded,
            existing_websites = seen_websites_disc,
            delivery          = req.delivery,
            extra             = effective_extra,
            target_count      = round_target,
        )

        # openai_claude_discover_vendors already uses: Serper→Groq, then GPT, then Claude Haiku, then Sonar
        discovered = openai_claude_discover_vendors(**_kw)
        discovered = [v for v in discovered if not is_b2c_vendor(v)]
        _plog(sid, f"  Groq→GPT→Claude pipeline found {len(discovered)} candidates")

        # Supplement with Claude Haiku pass if still short (Phase 2 already ran GPT)
        if len(discovered) < still_needed:
            _plog(sid, f"  Only {len(discovered)} — running Claude Haiku supplement pass")
            try:
                from services.web_search_discovery import _discover_single_country
                extra_batch = []
                for country in country_list:
                    batch = _discover_single_country(
                        req.description, req.part_number, req.brand,
                        req.channel_codes, all_excluded + [v["name"] for v in discovered],
                        country, req.extra_instructions, per_country_target,
                        channel_labels=channels_full, start_from="anthropic-haiku",
                    )
                    extra_batch.extend(batch)
                discovered = discovered + [v for v in extra_batch if not is_b2c_vendor(v)]
                _plog(sid, f"  After Claude Haiku: {len(discovered)} candidates")
            except Exception as e:
                print(f"  ⚠️  Claude Haiku supplement failed: {e}")

        # Groq last resort if GPT + Claude both returned < 3
        if len(discovered) < 3:
            _plog(sid, f"  GPT + Claude found < 3 — trying Groq last resort")
            discovered = groq_discover_vendors(**_kw)
            discovered = [v for v in discovered if not is_b2c_vendor(v)]
            _plog(sid, f"  Groq last resort found {len(discovered)} candidates")

        if not discovered:
            _plog(sid, "  No new candidates found in this pass")

        print(f"  📊 Round {_round}: {len(discovered)} candidates to process")

        # ── Relevance filter (FREE, Groq) ──────────────────────
        _plog(sid, f"[Step 2] Relevance filter — checking {len(discovered)} candidates (round {_round})")
        checkable = [v for v in discovered if v.get("source") != "manufacturer_direct"]
        if len(checkable) > 5:
            filtered = groq_relevance_filter(
                vendors=checkable, description=clean_desc,
                part_number=req.part_number, brand=req.brand, threshold=6,
            )
            # Safety: never drop everything — if filter kills all candidates keep the top half
            checkable = filtered if filtered else checkable
        mfr_only   = [v for v in discovered if v.get("source") == "manufacturer_direct"]
        candidates = mfr_only + checkable
        _plog(sid, f"  {len(candidates)} candidates passed relevance check")

        if not candidates:
            _plog(sid, "  All candidates filtered by relevance check")

        # ── Enrichment (PAID) ───────────────────────────────────
        _plog(sid, f"[Step 3] Contact enrichment — {len(candidates)} vendors (round {_round})")
        enriched = enrich_vendor_contacts(
            vendors        = candidates,
            description    = req.description,
            country        = country_str or "UAE",
            search_id      = sid,
            progress_store = _enrichment_progress,
        )

        # ── Accumulate verified vendors ─────────────────────────
        round_added = 0
        for v in enriched:
            if len(accumulated) >= effective_target:
                break
            name = v.get("name", "")
            norm = _normalize_company_name(name)
            if norm and norm in seen_names:
                continue
            if _is_blacklisted(name):
                print(f"  🚫 Blacklisted: {name}")
                continue
            site = (v.get("website") or "").strip().lower().rstrip("/")
            site_key = re.sub(r"^https?://(?:www\.)?", "", site)
            # Collapse subdomains to root domain for dedup (uae.company.com → company.com)
            site_parts = site_key.split(".")
            root_domain = ".".join(site_parts[-2:]) if len(site_parts) >= 2 else site_key
            if root_domain and root_domain in seen_websites:
                print(f"  ✂️  Duplicate website: {name} ({site_key})")
                continue
            if v.get("product_mismatch"):
                print(f"  🚫 Dropped (product mismatch): {name}")
                continue
            has_contact = _has_valid_email(v) or bool(v.get("website"))
            if (not is_b2c_vendor(v)
                    and name.lower().strip() not in existing_lower
                    and (has_contact or v.get("name"))):
                if norm:        seen_names.add(norm)
                if root_domain: seen_websites.add(root_domain)
                accumulated.append(v)
                round_added += 1

        # Exclude everything processed this round from the next round
        all_excluded    += [v.get("name","") for v in discovered]
        seen_websites_disc += [v.get("website","") for v in discovered if v.get("website")]

        _plog(sid, f"  Round {_round} added {round_added} verified suppliers (total: {len(accumulated)}/{effective_target})")


    final_vendors  = accumulated[:effective_target]
    verified_final = _verified_count(final_vendors)
    print(f"\n  ✅ Final: {len(final_vendors)}/{effective_target} target vendors ({verified_final} verified)")

    # RFQ scoring — Priority Rank + Response Probability + Quotation Speed
    _plog(sid, f"[Step 5] RFQ scoring — ranking {len(final_vendors)} vendors by quotation likelihood")
    final_vendors = _add_rfq_scores(final_vendors, req.description, country_str or "UAE")

    if not final_vendors:
        return {
            "success":            True,
            "vendors":            [],
            "query_summary":      f"AI discovery found no verified vendors for '{clean_desc[:80]}'. Check your supplier database for existing vendors.",
            "quality_metrics":    {},
            "deep_search_ran":    False,
            "claude_ran":         False,
            "target_vendor_count": effective_target,
            "verified_count":     0,
        }

    prompt_note = (
        f" | Your prompt was processed by GPT-4o-mini (→ Claude Haiku fallback)"
        if req.extra_instructions else ""
    )
    return {
        "success":            True,
        "vendors":            final_vendors,
        "query_summary": (
            f"Found {len(final_vendors)} verified vendors"
            + (f" across {len(country_list)} countries" if len(country_list) > 1 else "")
            + f" | Countries: {', '.join(country_list)}"
            + " | Discovery: GPT-4o-mini + Claude Haiku + Sonar (per country)"
            + " | Enrichment: BeautifulSoup crawl + Groq email parse + MX verify"
            + prompt_note
        ),
        "quality_metrics":     {},
        "deep_search_ran":     False,
        "claude_ran":          False,
        "target_vendor_count": effective_target,
        "verified_count":      verified_final,
    }