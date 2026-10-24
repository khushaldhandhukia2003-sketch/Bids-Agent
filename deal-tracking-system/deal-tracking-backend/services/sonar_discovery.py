"""
services/sonar_discovery.py

Direct Sonar-based vendor discovery.
Used as fallback when AI discovery produces hallucinated batches,
and as top-up source when verified vendor count is below target.
"""

import os
import re
import json
import requests
from typing import List, Dict, Optional

SONAR_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")

# ── B2C / non-B2B blocklist ───────────────────────────────────
B2C_BLOCKLIST_DOMAINS = {
    "noon.com", "amazon.com", "amazon.ae", "alibaba.com", "aliexpress.com",
    "ebay.com", "souq.com", "namshi.com", "carrefour.com", "lulu.com",
    "sharafdg.com", "jumbo.ae", "iherb.com", "dubizzle.com",
    "walmart.com", "target.com", "costco.com",
}

B2C_BLOCKLIST_KEYWORDS = {
    "amazon", "noon", "alibaba", "aliexpress", "ebay", "souq",
    "carrefour", "lulu hypermarket", "sharaf dg", "namshi",
}


def is_b2c_vendor(vendor: Dict) -> bool:
    """Returns True if vendor looks like a B2C marketplace."""
    name    = (vendor.get("name",    "") or "").lower()
    website = (vendor.get("website", "") or "").lower()
    for kw in B2C_BLOCKLIST_KEYWORDS:
        if kw in name:
            return True
    for domain in B2C_BLOCKLIST_DOMAINS:
        if domain in website:
            return True
    return False


def sonar_direct_discovery(
    description:      str,
    channel_codes:    List[str]     = None,
    delivery:         Optional[str] = None,
    existing_vendors: List[str]     = None,
    max_vendors:      int           = 15,
) -> List[Dict]:
    if not SONAR_API_KEY:
        print("  ⚠️  PERPLEXITY_API_KEY not set — cannot run Sonar direct discovery")
        return []

    country      = delivery or "UAE"
    channels_str = ", ".join(channel_codes) if channel_codes else "LAD, OEM, IGS, B2B"
    exclude_str  = "\n".join(f"- {v}" for v in (existing_vendors or [])[:20]) or "None"
    queries      = _build_sonar_queries(description, country)
    all_vendors  = []
    seen_names   = set()

    for i, query in enumerate(queries):
        print(f"  🌐 Sonar direct search [{i+1}/{len(queries)}]: {query[:80]}")
        vendors = _run_sonar_search(query, description, channels_str, exclude_str, country)
        for v in vendors:
            if is_b2c_vendor(v):
                print(f"      🚫 Blocked B2C: {v.get('name')}")
                continue
            name_norm = v.get("name", "").lower().strip()
            if name_norm and name_norm not in seen_names:
                seen_names.add(name_norm)
                all_vendors.append(v)
        if len(all_vendors) >= max_vendors:
            break

    print(f"  ✅ Sonar direct discovery: {len(all_vendors)} real vendors found")
    return all_vendors[:max_vendors]


def sonar_country_discover(
    description:    str,
    country:        str,
    extra:          Optional[str]  = None,
    existing_names: List[str]      = None,
    target_count:   int            = 5,
) -> List[Dict]:
    """
    Targeted Sonar live-web search for a specific country.
    Called when GPT + Claude both return < 3 vendors for a country.
    """
    if not SONAR_API_KEY:
        return []

    core         = _extract_core_product(description)
    exclude_str  = "\n".join(f"- {v}" for v in (existing_names or [])[:20]) or "None"
    user_req     = f"\nAlso note this buyer requirement: {extra}" if extra else ""
    channels_str = "LAD, OEM, IGS, B2B"

    queries = [
        f"{core} supplier {country} B2B industrial",
        f"{core} distributor {country} company",
    ]

    all_vendors: List[Dict] = []
    seen_names: set = set()

    for i, query in enumerate(queries):
        if len(all_vendors) >= target_count:
            break
        print(f"  🌐 Sonar [{country}] search [{i+1}/{len(queries)}]: {query[:80]}")

        prompt = f"""Search the web and find real B2B industrial supplier companies for:

Product: {description}
Country: {country.upper()} ONLY — return ONLY companies based in or with offices in {country.upper()}
Search query: {query}{user_req}

STRICT RULES:
- Companies MUST be physically located in or have a registered office in {country}
- Only B2B industrial suppliers, distributors, authorized dealers
- Do NOT include: Amazon, Noon, Alibaba, eBay, or any B2C marketplace
- Only companies you actually found via web search — do NOT invent names

Do NOT include:
{exclude_str}

For each company found return:
- name, website, country (their actual country), city, description, sourcing_rationale
- channel_code (one of: {channels_str}), confidence_score, email, phone

Return ONLY a valid JSON array. If none found, return []."""

        try:
            resp = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {SONAR_API_KEY}", "Content-Type": "application/json"},
                json={"model": "sonar", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1500},
                timeout=30,
            )
            if resp.status_code != 200:
                continue
            content = resp.json()["choices"][0]["message"]["content"].strip()
            clean   = re.sub(r"```json|```", "", content).strip()
            start   = clean.find("[")
            end     = clean.rfind("]")
            if start == -1 or end == -1:
                continue
            vendors = json.loads(clean[start:end+1])
            if not isinstance(vendors, list):
                continue
            for v in vendors:
                if is_b2c_vendor(v):
                    continue
                name_norm = v.get("name", "").lower().strip()
                if not name_norm or name_norm in seen_names:
                    continue
                seen_names.add(name_norm)
                v["source"] = "sonar_country"
                v.setdefault("email", "")
                v.setdefault("phone", "")
                v.setdefault("website", "")
                all_vendors.append(v)
        except Exception as e:
            print(f"  ⚠️  Sonar country search error: {e}")

    print(f"  ✅ Sonar country discover [{country}]: {len(all_vendors)} vendors")
    return all_vendors[:target_count]


def _build_sonar_queries(description: str, country: str) -> List[str]:
    core = _extract_core_product(description)
    return [
        f"{core} supplier {country} B2B industrial",
        f"{core} trader distributor {country} B2B",
        f"industrial {core} supplier {country}",
    ]


def _extract_core_product(description: str) -> str:
    """
    Fix 2: Improved extraction — removes model/part numbers more aggressively.

    "Ingersoll Rand 3940B2Ti 1 In. 2500 Ft-Lb Air Impact Wrench"
    → "ingersoll rand air impact wrench"

    "COTTON RAG,WHITE,50KG/BUNDLE,100% COTTON"
    → "cotton rag"
    """
    cleaned = description

    # Remove part/model numbers — any token containing both letters and digits
    # e.g. 3940B2Ti, ACS880-01, PR-26-B152, ABC-12345
    cleaned = re.sub(r'\b[A-Za-z0-9]*\d[A-Za-z0-9]*[-/][A-Za-z0-9]*\b', '', cleaned)  # hyphenated codes
    cleaned = re.sub(r'\b[A-Z]+\d+[A-Za-z0-9]*\b', '', cleaned)   # uppercase+digits: ACS880, 3940B2Ti
    cleaned = re.sub(r'\b\d+[A-Z][A-Za-z0-9]*\b', '', cleaned)    # digits+uppercase: 1In, 50KG

    # Remove measurements with units
    unit_pattern = (
        r'\d+(\.\d+)?(\s*/\s*\d+(\.\d+)?)?\s*'
        r'(kg|lbs?|lb|mm|cm|m\b|ft\b|sq|in\b|inch|pcs|ea|units?|bundle|roll|'
        r'bar|psi|hp|kw|kva|amps?|a\b|v\b|hz|rpm|nm|ft-lb|in-lb|°c|°f)'
    )
    cleaned = re.sub(unit_pattern, '', cleaned, flags=re.IGNORECASE)

    # Remove standalone numbers
    cleaned = re.sub(r'\b\d{2,}\b', '', cleaned)

    # Remove spec labels and their values
    cleaned = re.sub(
        r'\b(grade|type|size|material|spec(?:ification)?|model|part|no\.?|'
        r'ref\.?|mfg\.?|qty|uom|ea|dr\.?|sq\.?|ft\.?)\s*[:\-]?\s*\S*',
        '', cleaned, flags=re.IGNORECASE
    )

    # Remove separators and leftovers
    cleaned = re.sub(r'[,;|/\\%]+', ' ', cleaned)
    cleaned = re.sub(r'\b[-\.]\b', ' ', cleaned)      # lone hyphens/dots
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Keep meaningful words (>2 chars), take first 5
    words = [w for w in cleaned.split() if len(w) > 2 and not w.isdigit()]
    core  = " ".join(words[:5]) if words else description[:40]
    return core.lower()


def _run_sonar_search(
    query:        str,
    description:  str,
    channels_str: str,
    exclude_str:  str,
    country:      str,
) -> List[Dict]:
    prompt = f"""Search the web and find real B2B supplier companies for this product:

Product: {description}
Target region: {country} / Middle East / Gulf
Search query: {query}

IMPORTANT RULES:
- Only include B2B industrial suppliers, distributors, authorized dealers, trading companies
- Do NOT include B2C marketplaces: Amazon, Noon, Alibaba, eBay, Souq, Namshi, Carrefour
- Do NOT include retail stores
- Prefer companies based in UAE, Qatar, Saudi Arabia, Kuwait, Oman, Bahrain
- Only include companies you actually found in web search results

For each B2B company found:
- name: exact company name from website
- country: their country
- city: their city
- website: their actual B2B company website (NOT a product page on a marketplace)
- email: contact email from their website
- phone: phone number
- description: what they do
- sourcing_rationale: why they supply this product
- channel_code: one of [{channels_str}]
- confidence_score: 8.0
- source: "sonar_direct"

Do NOT include:
{exclude_str}

Return ONLY a valid JSON array of B2B companies. If none found, return []:"""

    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {SONAR_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "sonar",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 1500},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"      ⚠️  Sonar search error: {resp.status_code}")
            return []

        content = resp.json()["choices"][0]["message"]["content"].strip()
        clean   = re.sub(r"```json|```", "", content).strip()
        start   = clean.find("[")
        end     = clean.rfind("]")
        if start == -1 or end == -1:
            return []

        result  = json.loads(clean[start:end+1])
        vendors = result if isinstance(result, list) else []
        for v in vendors:
            v["source"] = "sonar_direct"
            v.setdefault("email",   "")
            v.setdefault("phone",   "")
            v.setdefault("website", "")
        return vendors

    except Exception as e:
        print(f"      ⚠️  Sonar direct search error: {e}")
        return []