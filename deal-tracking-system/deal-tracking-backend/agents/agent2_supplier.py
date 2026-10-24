# agents/agent2_supplier.py
"""
Agent 2 — Supplier Intelligence (UAE-Focused, Brand-Verified)

Strategy:
  - 3 parallel LLM calls using llama-3.1-8b-instant:
      Tier 1: OEM / Manufacturer offices / Authorized distributors  (12-15 vendors)
      Tier 2: Authorized dealers / Channel partners                 ( 8-10 vendors)
      Tier 3: UAE resellers explicitly advertising the exact brand  ( 5-7  vendors)
  - All tiers: UAE-only, brand-mandatory, contact from official website only
  - Deduplication by name across all tiers
  - Priority rank, RFQ response probability, quotation speed stored in DB
"""

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from agents.state import ProcurementState
from database import get_connection

CHANNEL_CODES = {
    "OEM / Manufacturer UAE Office":            "OEM",
    "Officially Authorized UAE Distributor":    "LAD",
    "Officially Authorized UAE Supplier":       "LAD",
    "Officially Authorized UAE Dealer":         "HOA",
    "Officially Authorized UAE Channel Partner":"HOA",
    "UAE Reseller / Authorization Not Verified":"GM",
    "UAE Sourcing Company":                     "CIS",
    "Local Authorized Distributors":            "LAD",
    "Grey Market / Parallel Import":            "GM",
    "OEM Direct Factory":                       "OEM",
    "Industrial Surplus Dealers":               "ISD",
    "Independent Global Stockists":             "IGS",
    "Industrial B2B Marketplaces":              "B2B",
    "Other Country Distributors":               "OCD",
    "Free Zone Trading Houses":                 "FZT",
    "Service & Repair Companies":               "SRC",
    "Online Retail / MRO E-commerce":           "MRO",
    "Project Subcontractor Excess":             "PSE",
    "Local Manufacturing / Reverse Engineering":"LMR",
    "Hidden Regional OEM Agents":               "HOA",
    "Buying Groups / Procurement Alliances":    "BGA",
    "Cross-Industry Suppliers":                 "CIS",
}

_AUTHORIZED_TYPES = {
    "OEM / Manufacturer UAE Office",
    "Officially Authorized UAE Distributor",
    "Officially Authorized UAE Supplier",
    "Officially Authorized UAE Dealer",
    "Officially Authorized UAE Channel Partner",
}

# Tier definitions
_TIER_1 = (
    "OEM / Manufacturer UAE Office",
    "Officially Authorized UAE Distributor",
    "Officially Authorized UAE Supplier",
)
_TIER_2 = (
    "Officially Authorized UAE Dealer",
    "Officially Authorized UAE Channel Partner",
)
_TIER_3 = (
    "UAE Reseller / Authorization Not Verified",
    "UAE Sourcing Company",
)


def _ask_llm_70b(prompt: str, temperature: float = 0.6) -> str:
    import os
    from groq import Groq

    keys = [k for k in [
        os.getenv("GROQ_API_KEY"),
        os.getenv("GROQ_API_KEY_2"),
        os.getenv("GROQ_API_KEY_3"),
    ] if k]

    last_err = None
    for key in keys:
        try:
            client = Groq(api_key=key)
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": (
                        "You are a B2B Industrial Sourcing and OEM Verification Specialist with deep "
                        "knowledge of the UAE, Gulf region, and global industrial supply chains. "
                        "You know real companies operating in Dubai, Abu Dhabi, Sharjah, and the UAE. "
                        "NEVER fabricate contact details. If you are unsure of a company's email or "
                        "phone, leave those fields as empty strings. "
                        "Always respond with valid JSON only."
                    )},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2500,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if "rate" in err_str or "429" in err_str or "quota" in err_str or "exhausted" in err_str:
                continue
            raise

    # All Groq keys exhausted — fall back to GPT-4o-mini
    print("  ⚠️  Groq exhausted — falling back to GPT-4o-mini")
    import openai
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError(f"All LLM providers failed. Last error: {last_err}")
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                "You are a B2B Industrial Sourcing and OEM Verification Specialist. "
                "You know real UAE companies. NEVER fabricate contact details. "
                "Always respond with valid JSON only."
            )},
            {"role": "user", "content": prompt},
        ],
        max_tokens=2500,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content.strip()


def _build_tier_prompt(
    tier_name: str,
    vendor_types: tuple,
    target_count: int,
    brand: str,
    part_number: str,
    description: str,
    product_category: str,
    key_specs: str,
    quantity: str,
    exclude_names: set,
) -> str:

    brand_line = f"Brand / Manufacturer: {brand}" if brand and brand.lower() not in ("any", "unknown", "") else "Brand: Any / as per specification"
    exclude_block = ""
    if exclude_names:
        sample = ", ".join(sorted(exclude_names)[:20])
        exclude_block = f"\nDO NOT suggest any of these already-known companies: {sample}\n"

    types_list = "\n".join(f"  - {t}" for t in vendor_types)

    return f"""
You are a B2B Industrial Sourcing and OEM Verification Specialist focused on the UAE market.

PRODUCT BEING SOURCED:
- {brand_line}
- Part Number   : {part_number}
- Description   : {description}
- Category      : {product_category}
- Key Specs     : {key_specs}
- Quantity      : {quantity}

YOUR TASK — {tier_name}:
Find exactly {target_count} REAL companies in the following categories ONLY:
{types_list}

MANDATORY RULES:
1. BRAND RULE: If a brand is specified, ONLY provide companies that supply THAT EXACT brand.
   Never suggest alternative or equivalent brands.
2. UAE ONLY: All companies must be operating in the UAE (Dubai, Abu Dhabi, Sharjah, Ajman,
   RAK, Fujairah, UAQ, Al Ain). A global company may be included ONLY if it has a UAE office,
   branch, or UAE-confirmed sales presence.
3. CONTACT RULE: Use only contact details from official company websites.
   - DO NOT use Google Maps, IndiaMART, Alibaba, TradeIndia, Made-in-China, or directories.
   - Email should be official domain-based (sales@, info@, uae@, middleeast@).
   - If you are not certain of the exact email or phone, leave the field as "".
   - Do NOT guess or generate likely email formats.
4. AUTHORIZATION: Only classify a company as "Officially Authorized" if you are confident
   that authorization is listed on the manufacturer's website or the company's own site.
   Otherwise use "UAE Reseller / Authorization Not Verified".
5. RANKING: Rank by priority — OEM first, then authorized distributors, then dealers,
   then unverified resellers. Start rank at {1 if tier_name == "Tier 1" else (16 if tier_name == "Tier 2" else 26)}.
{exclude_block}
Return JSON exactly:
{{
  "suppliers": [
    {{
      "priority_rank":            1,
      "name":                     "Exact official company name",
      "country":                  "United Arab Emirates",
      "city":                     "Dubai",
      "authorization_type":       "Must match one of the types listed above exactly",
      "email":                    "official@domain.com or empty string",
      "phone":                    "+971-x-xxx-xxxx or empty string",
      "website":                  "https://www.officialsite.com or empty string",
      "brands":                   "brands they stock relevant to this inquiry",
      "notes":                    "why this company and what confirms their UAE presence / authorization",
      "rfq_response_probability": "95% or 90% or 85% or 80% or 75% or 70% or 65%",
      "quotation_speed":          "Very High or High or Medium or Low",
      "confidence":               "high or medium or low"
    }}
  ]
}}

Rating guidance:
- rfq_response_probability: OEM office 95%, authorized distributor 90-85%, dealer 80-75%, reseller 70-65%
- quotation_speed: OEM office/strong distributor = Very High or High; dealer = Medium; reseller = Low
"""


def _fetch_preferred_suppliers(description: str, brand: str, division: str) -> list:
    try:
        keywords = []
        if brand and brand.lower() not in ("any", "unknown", ""):
            keywords.append(brand.lower())
        desc_words = [w.lower() for w in re.split(r'\W+', description or "") if len(w) > 4]
        keywords.extend(desc_words[:6])
        if not keywords:
            return []

        conn = get_connection()
        cur  = conn.cursor()
        like_clauses = " OR ".join(
            f"(LOWER(COALESCE(brands,'')) ILIKE %s OR LOWER(COALESCE(preferred_categories,'')) ILIKE %s OR LOWER(COALESCE(description,'')) ILIKE %s)"
            for _ in keywords
        )
        params = []
        for kw in keywords:
            params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])
        cur.execute(f"""
            SELECT vendor_name, country, city, email, phone, website,
                   brands, channel_codes, preferred_categories
            FROM vendors_master
            WHERE is_preferred = TRUE AND ({like_clauses})
            ORDER BY verification_confidence DESC NULLS LAST
            LIMIT 5
        """, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        preferred = []
        for r in rows:
            channel_label = (r[7] or "").split(",")[0].strip() or "Officially Authorized UAE Distributor"
            preferred.append({
                "id":                     str(uuid.uuid4()),
                "name":                   r[0],
                "country":                r[1] or "United Arab Emirates",
                "city":                   r[2] or "",
                "authorization_type":     channel_label,
                "supplier_type":          channel_label,
                "email":                  r[3] or "",
                "phone":                  r[4] or "",
                "website":                r[5] or "",
                "brands":                 r[6] or "",
                "notes":                  "⭐ Pre-agreed preferred supplier — check first before general sourcing",
                "confidence":             "high",
                "rfq_response_probability": "95%",
                "quotation_speed":        "Very High",
                "priority_rank":          0,
                "channel_code":           CHANNEL_CODES.get(channel_label, "LAD"),
                "is_preferred":           True,
            })
        if preferred:
            print(f"[Agent 2] ✅ {len(preferred)} preferred supplier(s) matched")
        return preferred
    except Exception as e:
        print(f"[Agent 2] ⚠️  Preferred supplier lookup failed: {e}")
        return []


def _call_tier(tier_name: str, vendor_types: tuple, target_count: int,
               brand: str, part_number: str, description: str,
               product_category: str, key_specs: str, quantity: str,
               exclude_names: set) -> list:
    prompt = _build_tier_prompt(
        tier_name, vendor_types, target_count,
        brand, part_number, description, product_category, key_specs, quantity,
        exclude_names,
    )
    try:
        raw  = _ask_llm_70b(prompt, temperature=0.6)
        data = json.loads(raw)
        results = data.get("suppliers", [])
        print(f"  [{tier_name}] → {len(results)} vendors returned")
        return results
    except Exception as e:
        print(f"  [{tier_name}] ⚠️  Failed: {e}")
        return []


def node_agent2(state: ProcurementState) -> ProcurementState:
    """
    Agent 2 — UAE-Focused Brand-Verified Supplier Intelligence.
    Runs 3 parallel LLM calls (Tier 1/2/3), deduplicates, ranks, saves.
    """
    print(f"[Agent 2] Starting UAE supplier discovery — {state['part_number']}")
    state["current_agent"] = "agent2"

    if state.get("error") and not state.get("db_inquiry_saved"):
        print("[Agent 2] Skipping — Agent 1 critical error")
        return state

    try:
        parsed   = state.get("parsed_specs", {})
        brand    = parsed.get("brand", "") or ""
        product_category = parsed.get("product_category", "Industrial Equipment")
        key_specs = str(parsed.get("key_specs", state.get("specs", "")))[:400]

        # ── 1. Preferred suppliers ────────────────────────
        preferred_suppliers = _fetch_preferred_suppliers(
            state["description"], brand, state.get("team", "")
        )
        state["preferred_suppliers"] = preferred_suppliers
        preferred_names = {s["name"].lower() for s in preferred_suppliers}
        exclude_names   = set(preferred_names)

        # ── 2. Parallel tier calls ────────────────────────
        print(f"[Agent 2] Running 3 parallel tier calls (70b model, UAE focus)...")

        common_kwargs = dict(
            brand            = brand,
            part_number      = state["part_number"],
            description      = state["description"],
            product_category = product_category,
            key_specs        = key_specs,
            quantity         = str(state.get("quantity", "")),
        )

        with ThreadPoolExecutor(max_workers=3) as pool:
            f1 = pool.submit(_call_tier, "Tier 1 — OEM & Authorized",     _TIER_1, 12, **common_kwargs, exclude_names=exclude_names)
            f2 = pool.submit(_call_tier, "Tier 2 — Dealers & Partners",   _TIER_2,  8, **common_kwargs, exclude_names=exclude_names)
            f3 = pool.submit(_call_tier, "Tier 3 — Resellers & Sourcing", _TIER_3,  6, **common_kwargs, exclude_names=exclude_names)
            tier1_results = f1.result()
            tier2_results = f2.result()
            tier3_results = f3.result()

        # ── 3. Deduplicate and tag ────────────────────────
        seen_names   = set(exclude_names)
        all_llm_suppliers = []

        for raw_list in [tier1_results, tier2_results, tier3_results]:
            for s in raw_list:
                name_lower = (s.get("name") or "").lower().strip()
                if not name_lower or name_lower in seen_names:
                    continue
                seen_names.add(name_lower)
                auth_type  = s.get("authorization_type", "UAE Reseller / Authorization Not Verified")
                s["id"]            = str(uuid.uuid4())
                s["inquiry_id"]    = state["inquiry_id"]
                s["supplier_type"] = auth_type
                s["channel_code"]  = CHANNEL_CODES.get(auth_type, "GM")
                s["is_preferred"]  = False
                s.setdefault("priority_rank", 99)
                s.setdefault("rfq_response_probability", "70%")
                s.setdefault("quotation_speed", "Medium")
                s.setdefault("phone", "")
                s.setdefault("website", "")
                s.setdefault("city", "")
                all_llm_suppliers.append(s)

        # Sort by priority_rank (preferred always first at rank 0)
        all_llm_suppliers.sort(key=lambda x: x.get("priority_rank") or 99)
        for s in preferred_suppliers:
            s["inquiry_id"] = state["inquiry_id"]

        suppliers = preferred_suppliers + all_llm_suppliers

        print(f"[Agent 2] ✅ {len(suppliers)} total "
              f"({len(preferred_suppliers)} preferred + {len(all_llm_suppliers)} discovered)")

        # ── 4. Save to PostgreSQL ─────────────────────────
        if suppliers:
            conn = get_connection()
            cur  = conn.cursor()
            for s in suppliers:
                cur.execute("""
                    INSERT INTO suppliers
                        (id, inquiry_id, name, country, city,
                         supplier_type, email, phone, website, brands, notes, channel_code,
                         priority_rank, rfq_response_probability, quotation_speed, authorization_type)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO NOTHING
                """, (
                    s["id"],
                    s["inquiry_id"],
                    s.get("name", ""),
                    s.get("country", "United Arab Emirates"),
                    s.get("city", ""),
                    s.get("supplier_type", ""),
                    s.get("email", ""),
                    s.get("phone", ""),
                    s.get("website", ""),
                    s.get("brands", ""),
                    s.get("notes", ""),
                    s.get("channel_code", "GEN"),
                    s.get("priority_rank"),
                    s.get("rfq_response_probability", ""),
                    s.get("quotation_speed", ""),
                    s.get("authorization_type", s.get("supplier_type", "")),
                ))
            conn.commit()
            cur.close()
            conn.close()

        state["suppliers"]      = suppliers
        state["supplier_count"] = len(suppliers)

    except Exception as e:
        state["error"]     = f"Agent 2 failed: {str(e)}"
        state["suppliers"] = []
        print(f"[Agent 2] ❌ Error: {e}")

    return state
