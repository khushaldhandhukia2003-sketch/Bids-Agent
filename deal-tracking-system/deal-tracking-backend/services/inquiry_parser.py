"""
services/inquiry_parser.py

Parses ANY inquiry document into structured data for supplier discovery.

No format is assumed. The document could be:
- A forwarded email with a table (like DEWA)
- A free-text description of one product
- A PDF extract with mixed content
- A list of items with no headers
- A scanned document OCR output
- A WhatsApp message copied as text
- An Excel copy-paste

The ONLY guaranteed output needed for supplier discovery is:
  - A list of item descriptions (even if just one)
  - A delivery location (defaults to UAE)

Everything else (client, dates, ref numbers) is extracted if present,
stored for records, but never required for the core flow to work.

Public functions:
  parse_inquiry_document(text)   → ParsedInquiry dict
  group_items_by_category(items) → List[CategoryGroup]
  score_supplier_coverage(...)   → suppliers with coverage scores added
"""

import json
import re
from typing import List, Optional
from services.openai_fallback import openai_parse_document, parsing_needs_fallback, parse_with_llm


# ── Parse prompt — open format, no assumptions ────────────────

PARSE_PROMPT = """You are a procurement assistant for an industrial trading company in UAE/Qatar.

Your job is to read ANY type of inquiry document and extract the items being requested.
The document could be an email, a table, free text, a scanned document, a forwarded message,
or any other format. Do not expect any specific structure.

PRIORITY: Extract EVERY SINGLE item/product being requested. This is the only thing that matters.
Do NOT stop early. Do NOT summarise. Extract ALL rows from the document — if there are 36 items, return 36 items.
Everything else (reference numbers, dates, client name) should be extracted if clearly present,
but do not fail or leave items empty if these are missing.

Return ONLY valid JSON in this exact structure:
{{
  "client": "company or person name if clearly mentioned, else null",
  "delivery": "delivery location or terms if mentioned, else null",
  "closing_date": "any deadline or closing date if mentioned, else null",
  "notes": "any important requirements, approvals needed, or instructions, else null",
  "items": [
    {{
      "description": "the product/item being requested — copy as much detail as available",
      "reference":   "any reference number, part number, RFX number, PO number attached to this item, else null",
      "quantity":    "quantity if mentioned, else null",
      "unit":        "unit of measure if mentioned, else null",
      "closing_date":"item-specific deadline if different from document deadline, else null"
    }}
  ]
}}

Critical rules:
- ALWAYS populate the items array — this is the most important field
- If the whole document describes ONE product, return one item
- If there is a LIST of products (even without headers or formatting), return one item per product
- description must never be null or empty — use whatever text describes what is being requested
- If you cannot tell items apart, put everything in one item description rather than returning empty
- Do not invent data — if a field is not in the document, set it to null
- Delivery location: extract from document, or return null (caller will default to UAE)
- Keep descriptions exactly as written — do not paraphrase or shorten

Document to parse:
{text}"""


def parse_inquiry_document(text: str) -> dict:
    """
    Takes raw text from ANY inquiry document.
    Returns structured ParsedInquiry with at minimum a list of item descriptions.

    Never raises — returns a fallback structure on any error so the flow continues.
    """
    if not text or not text.strip():
        return _empty_inquiry("Empty document text received")

    print(f"\n  Parsing inquiry document ({len(text)} chars)...")

    # Strip irrelevant Excel columns before sending to LLM
    if "|" in text:
        from services.openai_fallback import _compress_excel_text
        compressed = _compress_excel_text(text)
        print(f"  Compressed: {len(text)} → {len(compressed)} chars")
    else:
        compressed = text
    prompt = PARSE_PROMPT.format(text=compressed[:10000])

    # Try Groq first (~2s vs 10-15s for Claude)
    raw = None
    try:
        from services.groq_client import ask_groq
        raw = ask_groq(prompt, json_mode=True, max_tokens=2500)
        print("  Using Groq for inquiry parse")
    except Exception as ge:
        print(f"  Groq failed ({ge}), falling back to Claude/GPT")

    try:
        if raw is None:
            raw = parse_with_llm(prompt, max_tokens=2500)
        result = _safe_json(raw)

        if not isinstance(result, dict):
            return _empty_inquiry("Parser returned non-dict response")

        raw_items = result.get("items") or []

        cleaned_items = []
        for item in raw_items:
            desc = _clean(item.get("description"))
            if not desc:
                continue
            cleaned_items.append({
                "description":  desc,
                "reference":    _clean(item.get("reference")),
                "quantity":     _clean(item.get("quantity")),
                "unit":         _clean(item.get("unit")),
                "closing_date": _clean(item.get("closing_date")),
            })

        if not cleaned_items:
            print("  Warning: no items extracted — using full document as single item")
            cleaned_items = [{
                "description":  text[:300].strip(),
                "reference":    None,
                "quantity":     None,
                "unit":         None,
                "closing_date": None,
            }]

        parsed = {
            "client":        _clean(result.get("client")),
            "delivery":      _clean(result.get("delivery")) or "UAE",
            "closing_date":  _clean(result.get("closing_date")),
            "notes":         _clean(result.get("notes")),
            "is_multi_item": len(cleaned_items) > 1,
            "item_count":    len(cleaned_items),
            "items":         cleaned_items,
        }

        print(f"  Extracted {len(cleaned_items)} item(s)"
              f" | client: {parsed['client'] or 'unknown'}"
              f" | delivery: {parsed['delivery']}")

        return parsed

    except Exception as e:
        print(f"  Parse error: {e}")
        return _empty_inquiry(str(e), raw_text=text)


# ── Group items into product categories ───────────────────────

GROUP_PROMPT = """You are an industrial procurement specialist for a UAE trading company.

Group these inquiry items into product categories.
The goal: items in the same category can be sourced from the SAME TYPE of supplier.

Examples of good grouping:
- Check valves + gate valves + ball valves → "Valves & Fittings"
- Electrical cables + cable stocks → "Cables & Electrical"
- Steel sheets + metal plates → "Metals & Structural"
- Flow meters + pressure gauges → "Instrumentation"
- Bearings + rollers + mechanical parts → "Mechanical Components"

Items:
{items_json}

Return ONLY a valid JSON array:
[
  {{
    "category_name": "Short descriptive name",
    "category_code": "SNAKE_CASE_CODE",
    "suggested_channels": ["LAD", "OEM"],
    "item_indices": [0, 2, 5]
  }}
]

Rules:
- item_indices are 0-based positions in the items array above
- Every item index must appear in exactly one category
- Merge aggressively — fewer categories is better
- If in doubt about two items, put them in the same category
- suggested_channels must only be from: LAD, GM, OCD, OEM, ISD, IGS, FZT, B2B, HOA, SRC
- Pick channels that make sense for that type of industrial product
- category_code: uppercase letters and underscores only, max 15 chars
- If all items are from the same industry, one category is fine"""


def group_items_by_category(parsed_inquiry: dict) -> List[dict]:
    """
    Takes a ParsedInquiry and returns CategoryGroups.

    Single-item inquiries skip the LLM call and return one group.
    If grouping fails, returns one group with all items.
    """
    items = parsed_inquiry.get("items", [])

    if not items:
        return []

    if len(items) == 1:
        return [_wrap_as_single_group(items)]

    print(f"  Grouping {len(items)} items into product categories...")

    items_for_prompt = [
        {"index": i, "description": item["description"]}
        for i, item in enumerate(items)
    ]

    prompt = GROUP_PROMPT.format(
        items_json=json.dumps(items_for_prompt, indent=2)
    )

    try:
        raw    = parse_with_llm(prompt, max_tokens=2000)
        groups = _safe_json(raw)

        # Handle if LLM wrapped the array in an object
        if isinstance(groups, dict):
            for key in ("categories", "groups", "result"):
                if key in groups and isinstance(groups[key], list):
                    groups = groups[key]
                    break
            else:
                for v in groups.values():
                    if isinstance(v, list):
                        groups = v
                        break
                else:
                    raise ValueError("Could not find array in response")

        result   = []
        assigned = set()

        for g in groups:
            indices   = [i for i in g.get("item_indices", []) if i < len(items)]
            grp_items = [items[i] for i in indices]
            if not grp_items:
                continue
            assigned.update(indices)
            result.append({
                "category_name":      g.get("category_name", "General"),
                "category_code":      _sanitize_code(g.get("category_code", "GENERAL")),
                "suggested_channels": g.get("suggested_channels") or ["LAD", "OEM", "IGS"],
                "item_count":         len(grp_items),
                "items":              grp_items,
            })

        # Any items missed by Groq go into a catch-all
        unassigned = [items[i] for i in range(len(items)) if i not in assigned]
        if unassigned:
            result.append({
                "category_name":      "Other Items",
                "category_code":      "OTHER",
                "suggested_channels": ["LAD", "B2B", "IGS"],
                "item_count":         len(unassigned),
                "items":              unassigned,
            })

        print(f"  Grouped into {len(result)} categories: "
              f"{[g['category_name'] for g in result]}")
        return result

    except Exception as e:
        print(f"  Grouping error: {e} — falling back to single group")
        return [_wrap_as_single_group(items)]


# ── Score suppliers by item coverage ─────────────────────────

def score_supplier_coverage(
    suppliers:       List[dict],
    category_groups: List[dict],
) -> List[dict]:
    """
    Adds coverage metadata to each supplier and re-sorts by blended score.

    coverage_score  = % of total inquiry items the supplier's category covers
    blended_score   = 60% coverage + 40% confidence

    A supplier covering 6/8 items ranks above one covering 1/8 even if the
    latter has a higher confidence score.
    """
    total_items = sum(g.get("item_count", 0) for g in category_groups)

    if total_items == 0 or not suppliers:
        return suppliers

    # Map: category_code → {count, descriptions}
    cat_map = {}
    for g in category_groups:
        code = _sanitize_code(g.get("category_code", "GENERAL"))
        cat_map[code] = {
            "count":        g.get("item_count", 0),
            "descriptions": [item["description"] for item in g.get("items", [])],
        }

    for sup in suppliers:
        # Try channel_code first (from vendor_discovery), then category_code
        code      = _sanitize_code(
            sup.get("channel_code") or sup.get("category_code") or ""
        )
        cat_data  = cat_map.get(code, {"count": 0, "descriptions": []})
        covered   = cat_data["count"]

        raw_coverage = covered / total_items
        confidence   = float(
            sup.get("confidence_score") or sup.get("score") or 5
        ) / 10.0

        sup["coverage_score"]     = round(raw_coverage * 100)  # 0–100%
        sup["covered_item_count"] = covered
        sup["total_item_count"]   = total_items
        sup["covered_items"]      = cat_data["descriptions"]
        sup["blended_score"]      = round(raw_coverage * 0.6 + confidence * 0.4, 3)

    suppliers.sort(key=lambda x: x.get("blended_score", 0), reverse=True)
    return suppliers


# ── Helpers ───────────────────────────────────────────────────

def _clean(val) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("null", "none", "n/a", "-", "") else None


def _sanitize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "_", (code or "GENERAL").upper())[:15]


def _safe_json(text: str):
    text = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = text.find(start_char)
            end   = text.rfind(end_char)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue
    raise ValueError(f"Could not parse JSON: {text[:300]}")


def _empty_inquiry(reason: str, raw_text: str = "") -> dict:
    """Returns a minimal valid ParsedInquiry when parsing completely fails."""
    items = []
    if raw_text.strip():
        items = [{
            "description":  raw_text[:300].strip(),
            "reference":    None,
            "quantity":     None,
            "unit":         None,
            "closing_date": None,
        }]
    return {
        "client":        None,
        "delivery":      "UAE",
        "closing_date":  None,
        "notes":         None,
        "is_multi_item": False,
        "item_count":    len(items),
        "items":         items,
        "parse_error":   reason,
    }


def _wrap_as_single_group(items: List[dict]) -> dict:
    return {
        "category_name":      "General Procurement",
        "category_code":      "GENERAL",
        "suggested_channels": ["LAD", "OEM", "IGS", "B2B"],
        "item_count":         len(items),
        "items":              items,
    }