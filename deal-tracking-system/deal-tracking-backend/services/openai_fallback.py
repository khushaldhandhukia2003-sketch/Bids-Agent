"""
services/openai_fallback.py

OpenAI integration — fallback and precision layer only.
NOT called on every request. Only triggered when:

  1. Groq extraction fails (malformed JSON, missing fields, avg_conf < 0.6)
  2. Groq API times out or hits rate limit
  3. Agent 1 parsing quality is low (< 3 fields, no items found)
  4. Consensus mode explicitly requested (manual trigger)

Models used:
  - gpt-4o-mini  → extraction fallback, parsing fallback (cheap, fast)
  - gpt-4o       → consensus comparison only (expensive, manual trigger)

Contact data policy:
  Discovery prompts NEVER ask for email, phone, or website.
  These fields are populated downstream by contact_enrichment.py
  (webcrawl → Sonar fallback). LLM-generated contacts are unreliable.
"""

import os
import re
import json
from typing import List, Dict, Optional

OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def _call_claude(prompt: str, max_tokens: int = 2000) -> str:
    """Call Claude Haiku for parsing tasks — fast and cheap."""
    if not ANTHROPIC_API_KEY:
        raise Exception("ANTHROPIC_API_KEY not set")
    import anthropic
    client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model      = "claude-haiku-4-5-20251001",
        max_tokens = max_tokens,
        messages   = [{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def parse_with_llm(prompt: str, max_tokens: int = 2000) -> str:
    """
    Parse/extract using Claude (primary) → GPT-4o-mini (fallback).
    Use this for ALL document parsing — keeps Groq free for vendor discovery.
    """
    # 1. Claude Haiku
    try:
        result = _call_claude(prompt, max_tokens=max_tokens)
        print(f"  ✅ Claude parsed ({len(result)} chars)")
        return result
    except Exception as e:
        print(f"  ⚠️  Claude parse failed ({e}) — trying GPT-4o-mini")

    # 2. GPT-4o-mini
    try:
        result = _call_openai(prompt, model="gpt-4o-mini", max_tokens=max_tokens)
        print(f"  ✅ GPT-4o-mini parsed ({len(result)} chars)")
        return result
    except Exception as e:
        raise Exception(f"All parse models failed. Last error: {e}")


def parse_with_llm_vision(data_url: str, prompt: str, max_tokens: int = 2000) -> str:
    """
    Vision parsing: Claude (primary) → GPT-4o-mini (fallback).
    """
    # 1. Claude — send image as base64
    try:
        if ANTHROPIC_API_KEY:
            import anthropic, base64, re as _re
            # Extract media type and raw base64 from data URL
            m = _re.match(r'data:([^;]+);base64,(.+)', data_url, _re.DOTALL)
            if m:
                media_type = m.group(1)
                img_b64    = m.group(2)
                client     = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                response   = client.messages.create(
                    model      = "claude-haiku-4-5-20251001",
                    max_tokens = max_tokens,
                    messages   = [{"role": "user", "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": media_type, "data": img_b64,
                        }},
                        {"type": "text", "text": prompt},
                    ]}],
                )
                extracted = response.content[0].text.strip()
                print(f"  ✅ Claude vision extracted {len(extracted)} chars")
                return extracted
    except Exception as e:
        print(f"  ⚠️  Claude vision failed ({e}) — trying GPT-4o-mini")

    # 2. GPT-4o-mini vision
    try:
        result = _call_openai_vision(data_url, prompt, max_tokens=max_tokens)
        print(f"  ✅ GPT-4o-mini vision extracted {len(result)} chars")
        return result
    except Exception as e:
        raise Exception(f"Vision parse failed: {e}")


def _call_openai(prompt: str, model: str = "gpt-4o-mini", max_tokens: int = 1500) -> str:
    if not OPENAI_API_KEY:
        # Skip straight to Anthropic Haiku if no OpenAI key
        from services.llm_router import ask_llm
        return ask_llm(prompt, json_mode=False, max_tokens=max_tokens,
                       start_from="anthropic-haiku")

    try:
        import openai
        client   = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()

    except Exception as exc:
        msg = str(exc).lower()
        is_exhausted = any(p in msg for p in (
            "rate limit", "rate_limit", "quota", "too many requests",
            "429", "insufficient_quota", "exceeded", "billing",
        ))
        if is_exhausted:
            print(f"  ⚠️  OpenAI exhausted ({str(exc)[:80]}) — switching to Anthropic Haiku")
            from services.llm_router import ask_llm
            return ask_llm(prompt, json_mode=False, max_tokens=max_tokens,
                           start_from="anthropic-haiku")
        raise


def _call_openai_vision(data_url: str, prompt: str, max_tokens: int = 2000) -> str:
    """Call OpenAI gpt-4o-mini with a base64 image for text extraction."""
    if not OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY not set")
    import openai
    client   = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini", max_tokens=max_tokens,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text",      "text": prompt},
        ]}],
    )
    return response.choices[0].message.content.strip()


# ── Trigger 1: Extraction Fallback ────────────────────────────

def openai_extract_suppliers(
    search_results: List[Dict],
    description:    str,
    channel_codes:  List[str] = None,
) -> List[Dict]:
    """
    Called when Groq extraction returns malformed JSON, < 3 vendors,
    or avg confidence < 0.6.

    CONTACT DATA POLICY: Does NOT extract contact details.
    Contact enrichment is handled separately by contact_enrichment.py.
    """
    if not search_results:
        return []

    formatted = "\n".join([
        f"[{i+1}] Title: {r.get('title','')}\n    Snippet: {r.get('snippet','')}\n    URL: {r.get('link','')}"
        for i, r in enumerate(search_results[:15])
    ])
    channels_hint = ", ".join(channel_codes) if channel_codes else "LAD, OEM, IGS, OCD, ISD, B2B"

    prompt = f"""You are a procurement data extraction specialist.

Extract ONLY real supplier companies from these search results.
Item to source: {description}
Preferred channels: {channels_hint}

SEARCH RESULTS:
{formatted}

STRICT RULES:
- Extract ONLY companies explicitly named in titles or snippets above
- DO NOT invent or guess company names
- DO NOT include directories (Alibaba, Yellow Pages, Made-in-China, Thomasnet)
- Focus on: authorized distributors, stockists, dealers, specialist trading companies
- The company MUST be directly relevant to sourcing: {description}
- If a company is a general trading house with no clear link to this product type, EXCLUDE it
- Prefer UAE / Qatar / Middle East

DO NOT include email, phone, or website — these will be fetched separately.

Return ONLY a valid JSON array. No markdown:
[{{
  "name": "Company Name",
  "country": "UAE",
  "city": "Dubai",
  "channel_code": "LAD",
  "confidence_score": 8.5,
  "relevance_reason": "Specific reason why this company would stock this exact product type",
  "email": "",
  "phone": "",
  "website": ""
}}]

If no valid suppliers found, return: []"""

    try:
        raw    = _call_openai(prompt, model="gpt-4o-mini", max_tokens=2500)
        clean  = re.sub(r"```json|```", "", raw).strip()
        try:
            result = json.loads(clean)
        except json.JSONDecodeError:
            last = clean.rfind('},')
            result = json.loads(clean[:last+1] + ']') if last > 0 else []
        vendors = result if isinstance(result, list) else []
        for v in vendors:
            v["source"] = "openai_extraction"
            v["email"]  = ""
            v["phone"]  = ""
            v["website"] = ""
        print(f"  🔁 OpenAI extraction fallback: {len(vendors)} vendors")
        return vendors
    except Exception as e:
        print(f"  ⚠️  OpenAI extraction fallback failed: {e}")
        return []


# ── Trigger 2: Groq Timeout / Rate Limit Fallback ─────────────

def openai_discover_vendors(
    description:      str,
    part_number:      Optional[str],
    brand:            Optional[str],
    channel_codes:    List[str],
    existing_vendors: List[str],
    delivery:         Optional[str],
    extra:            Optional[str],
    call_type:        str = "sourcing",
) -> List[Dict]:
    """
    Full replacement for Groq sourcing or ranking call when Groq fails.

    CONTACT DATA POLICY:
    Returns company identity only (name, location, channel, rationale).
    Email/phone/website are intentionally empty — contacts are fetched
    by contact_enrichment.py after relevance filtering.
    """
    channels_str = ", ".join(channel_codes) if channel_codes else "LAD, OEM, IGS, OCD, ISD, B2B"
    exclude_str  = "\n".join(f"- {v}" for v in existing_vendors[:20]) if existing_vendors else "None"
    extra_str    = f"\nAdditional requirement: {extra}" if extra else ""
    delivery_str = delivery or "UAE"

    if call_type == "ranking":
        task  = "Identify the 10-12 highest-confidence suppliers. Prefer OEM and authorized distributors."
        count = "10-12"
    else:
        task  = "Find 18-20 diverse supplier companies across the specified channels."
        count = "18-20"

    prompt = f"""You are a procurement sourcing agent for an industrial trading company in Dubai.

{task}

Item: {description}
Part Number: {part_number or 'N/A'}
Brand: {brand or 'Unknown'}
Delivery: {delivery_str}{extra_str}
Channels: {channels_str}

Already found — DO NOT repeat:
{exclude_str}

STRICT RELEVANCE RULE:
Only include a company if you are confident it specifically handles this product type.
Do NOT include general industrial traders unless they specifically stock this category.
A wrong but plausible-sounding company wastes the procurement engineer's time.

Find {count} NEW companies. Prioritize UAE/Qatar first, then Middle East, then global.

IMPORTANT: DO NOT include email, phone, or website — verified separately.

Return ONLY valid JSON array, no markdown:
[{{
  "name": "exact company name",
  "country": "UAE or Qatar etc",
  "city": "Dubai or Abu Dhabi etc",
  "brands": "specific brands they handle",
  "channel_code": "one of [{channels_str}]",
  "confidence_score": 7.5,
  "sourcing_rationale": "specific reason this company would supply this exact item",
  "description": "what this company does and their specialization",
  "source": "openai_fallback",
  "email": "",
  "phone": "",
  "website": ""
}}]"""

    try:
        raw    = _call_openai(prompt, model="gpt-4o-mini", max_tokens=3000)
        clean  = re.sub(r"```json|```", "", raw).strip()
        try:
            result = json.loads(clean)
        except json.JSONDecodeError:
            last = clean.rfind('},')
            result = json.loads(clean[:last+1] + ']') if last > 0 else []
        vendors = result if isinstance(result, list) else []
        print(f"  🔁 OpenAI {call_type} fallback: {len(vendors)} vendors")
        return vendors
    except Exception as e:
        print(f"  ⚠️  OpenAI {call_type} fallback failed: {e}")
        return []


# ── Trigger 3: Agent 1 Parsing Fallback ───────────────────────

def _compress_excel_text(text: str) -> str:
    """
    Strips Excel text down to only columns relevant for item extraction.
    """
    lines = text.split("\n")
    if not lines:
        return text

    header_idx  = None
    header_cols = []
    for i, line in enumerate(lines):
        if "|" not in line:
            continue
        parts = [p.strip().lower() for p in line.split("|")]
        if any(k in " ".join(parts) for k in ["description", "name", "item", "material"]):
            header_idx  = i
            header_cols = [p.strip() for p in line.split("|")]
            break

    if header_idx is None:
        cleaned = []
        for line in lines:
            if set(line.strip()) <= {"-", "=", " ", "|"}:
                continue
            parts     = [p.strip() for p in line.split("|")]
            non_empty = [p for p in parts if p and p not in ("nan", "None", "0.0", "")]
            if non_empty:
                cleaned.append(" | ".join(non_empty))
        return "\n".join(cleaned)

    keep_keywords = ["number","no","item","sl","description","name","material","quantity","qty","unit","uom","measure","part","reference","ref","code"]
    skip_keywords = ["incoterm","payment","delivery","date","warranty","discount","attachment","comment","ship","country","origin","brand","make","lead","currency","price","respond","reason","bid","proposal"]

    keep_indices = []
    for idx, col in enumerate(header_cols):
        col_lower = col.lower()
        if any(k in col_lower for k in keep_keywords):
            keep_indices.append(idx)
        elif any(s in col_lower for s in skip_keywords):
            continue
        elif len(col) < 10 and col.strip():
            keep_indices.append(idx)

    if len(keep_indices) < 2:
        keep_indices = list(range(min(5, len(header_cols))))

    cleaned = []
    for line in lines[:header_idx]:
        if line.strip() and "|" not in line:
            cleaned.append(line.strip())

    filtered_header = " | ".join(header_cols[i] for i in keep_indices if i < len(header_cols))
    cleaned.append(filtered_header)
    cleaned.append("-" * 40)

    for line in lines[header_idx + 1:]:
        if set(line.strip()) <= {"-", "=", " ", "|"}:
            continue
        parts    = [p.strip() for p in line.split("|")]
        row_vals = [parts[i] if i < len(parts) else "" for i in keep_indices]
        non_empty = [v for v in row_vals if v and v not in ("nan", "None", "0.0")]
        if non_empty:
            cleaned.append(" | ".join(row_vals))

    return "\n".join(cleaned)


def openai_parse_document(text: str) -> Dict:
    """
    Called when Groq document parsing returns poor quality.
    Uses gpt-4o. Returns same schema as parse_inquiry_document().
    """
    prompt = f"""You are a procurement document parser.

Extract all line items from this inquiry document.

DOCUMENT:
{_compress_excel_text(text)[:10000]}

Extract:
- client name (if mentioned)
- delivery location
- closing/due date
- any important notes or conditions
- ALL line items with: description, reference/part number, quantity, unit

CRITICAL: Extract EVERY SINGLE row. Do NOT stop early. Do NOT summarise.

Return ONLY valid JSON, no markdown:
{{
  "client": "client name or null",
  "delivery": "location or UAE",
  "closing_date": "date or null",
  "notes": "important notes or null",
  "is_multi_item": true,
  "item_count": 0,
  "items": [
    {{
      "description": "item description",
      "reference": "part number or null",
      "quantity": "quantity or null",
      "unit": "unit or null"
    }}
  ]
}}"""

    try:
        raw    = _call_openai(prompt, model="gpt-4o", max_tokens=6000)
        clean  = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(clean)
        items  = result.get("items", [])
        print(f"  🔁 OpenAI parsing fallback: {len(items)} items extracted")
        result["item_count"]    = len(items)
        result["is_multi_item"] = len(items) > 1
        result["parse_error"]   = None
        return result
    except Exception as e:
        print(f"  ⚠️  OpenAI parsing fallback failed: {e}")
        return {"client": None, "delivery": "UAE", "closing_date": None,
                "notes": None, "is_multi_item": False, "item_count": 0,
                "items": [], "parse_error": str(e)}


# ── Trigger 4: Consensus Comparison (manual trigger only) ──────

def consensus_compare(
    groq_vendors:   List[Dict],
    openai_vendors: List[Dict],
    description:    str,
    channel_codes:  List[str] = None,
) -> List[Dict]:
    """
    Optional consensus layer. NOT called automatically.
    Only triggered when engineer requests "deep search".
    """
    if not groq_vendors and not openai_vendors:
        return []

    channels_hint = ", ".join(channel_codes) if channel_codes else "LAD, OEM, IGS"
    combined      = groq_vendors + openai_vendors
    combined_json = json.dumps(combined, indent=2)

    prompt = f"""You are a senior procurement analyst.

Two AI systems independently found suppliers for: {description}
Channels: {channels_hint}

COMBINED SUPPLIER LIST (may contain duplicates):
{combined_json}

YOUR TASK:
1. Merge duplicate companies (same company, different spellings)
2. Score each unique company 0.0-10.0 based on relevance to: {description}
3. Remove companies with score < 5.0
4. Sort by score descending
5. Keep maximum 30 best vendors

DO NOT include email, phone, or website in the output.

Return ONLY valid JSON array:
[{{
  "name":"...","country":"...","city":"...",
  "brands":"...","channel_code":"...","confidence_score":0.0,
  "sourcing_rationale":"...","source":"consensus",
  "email":"","phone":"","website":""
}}]"""

    try:
        raw    = _call_openai(prompt, model="gpt-4o", max_tokens=4000)
        clean  = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(clean)
        vendors = result if isinstance(result, list) else combined
        print(f"  🤝 Consensus: {len(groq_vendors)} + {len(openai_vendors)} → {len(vendors)} final")
        return vendors
    except Exception as e:
        print(f"  ⚠️  Consensus failed: {e} — returning merged list")
        return combined


# ── Deep Discovery ─────────────────────────────────────────────

def openai_deep_discovery(
    description:      str,
    part_number:      Optional[str],
    brand:            Optional[str],
    channel_codes:    List[str],
    existing_vendors: List[str],
    delivery:         Optional[str],
    extra:            Optional[str],
) -> List[Dict]:
    """
    Regional deep discovery using UAE/GCC industrial market knowledge.
    Called when primary discovery returns weak results.

    CONTACT DATA POLICY: Returns company identity only.
    Email/phone/website are populated by contact_enrichment.py downstream.
    """
    channels_str = ", ".join(channel_codes) if channel_codes else "LAD, OEM, IGS, OCD, ISD, B2B"
    exclude_str  = "\n".join(f"- {v}" for v in existing_vendors[:30]) if existing_vendors else "None"
    extra_str    = f"\nAdditional requirement: {extra}" if extra else ""
    delivery_str = delivery or "UAE"
    brand_str    = f"Brand: {brand}" if brand else ""
    part_str     = f"Part Number: {part_number}" if part_number else ""

    prompt = f"""You are a senior procurement specialist with 15+ years experience in the UAE and Middle East industrial market.

You have deep knowledge of:
- UAE Free Zones: Jebel Ali (JAFZA), Dubai Airport Free Zone (DAFZA), Sharjah Airport Free Zone
- Major industrial distributors in Dubai, Abu Dhabi, Sharjah, Doha
- OEM authorized dealer networks for industrial equipment across the GCC
- Trading companies that specialize in HVAC, electrical, instrumentation, valves, pumps, compressors
- The grey market and parallel import networks for hard-to-find parts
- Key industrial areas: Al Quoz, Ras Al Khor, Mussafah (Abu Dhabi), Doha Industrial Area

ITEM TO SOURCE:
Description: {description}
{part_str}
{brand_str}
Delivery: {delivery_str}{extra_str}

SOURCING CHANNELS: {channels_str}

VENDORS ALREADY FOUND — DO NOT REPEAT:
{exclude_str}

STRICT RELEVANCE REQUIREMENT:
Only include a company if it specifically operates in the product category of: {description}
A general UAE industrial trader with no specific link to this product type must be EXCLUDED.
It is better to return 8 highly relevant companies than 15 generic ones.

Think step by step:
1. What is the exact product category?
2. Who are the OEM manufacturers?
3. Who are their authorized distributors in UAE/Qatar/GCC?
4. Which UAE specialist traders in Al Quoz, Ras Al Khor, or Jebel Ali handle this category?
5. Are there regional specialist stockists or MRO suppliers?

Find 12-15 NEW suppliers NOT in the excluded list.

IMPORTANT: DO NOT include email, phone, or website — verified separately.

Return ONLY valid JSON array, no markdown:
[{{
  "name": "exact company name",
  "country": "UAE or Qatar etc",
  "city": "Dubai or Abu Dhabi etc",
  "brands": "brands or product lines they specifically handle",
  "channel_code": "one of [{channels_str}]",
  "confidence_score": 7.0,
  "sourcing_rationale": "specific reason this company would stock this exact item type",
  "description": "what this company does and their specialization",
  "source": "openai_deep",
  "email": "",
  "phone": "",
  "website": ""
}}]"""

    try:
        raw    = _call_openai(prompt, model="gpt-4o-mini", max_tokens=3500)
        clean  = re.sub(r"```json|```", "", raw).strip()
        try:
            result = json.loads(clean)
        except json.JSONDecodeError:
            last = clean.rfind('},')
            result = json.loads(clean[:last+1] + ']') if last > 0 else []
        vendors = result if isinstance(result, list) else []
        print(f"  🔍 OpenAI deep discovery: {len(vendors)} vendors")
        return vendors
    except Exception as e:
        print(f"  ⚠️  OpenAI deep discovery failed: {e}")
        return []


# ── Quality check helpers ─────────────────────────────────────

def extraction_needs_fallback(vendors: List[Dict], threshold: float = 6.0) -> bool:
    if not vendors or len(vendors) < 3:
        return True
    scores  = [v.get("confidence_score") or 0.5 for v in vendors]
    avg     = sum(scores) / len(scores)
    if avg < threshold:
        return True
    missing = sum(1 for v in vendors if not v.get("name") or not v.get("country"))
    if missing > len(vendors) * 0.5:
        return True
    return False


def parsing_needs_fallback(parsed: Dict) -> bool:
    if not parsed:
        return True
    items = parsed.get("items", [])
    if len(items) == 0:
        return True
    empty_items = sum(1 for it in items if not it.get("description"))
    if empty_items > len(items) * 0.5:
        return True
    return False