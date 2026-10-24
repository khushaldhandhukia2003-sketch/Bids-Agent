"""
services/web_search_discovery.py

LLM-based vendor discovery.

Flow:
  1. Groq (llama-3.3-70b-versatile) — primary LLM discovery per country
  2. GPT-4o-mini                    — gap-fill when Groq finds < target
  3. Claude Haiku                   — supplement when both above find < 3
  4. Sonar (Perplexity)             — paid live-web last resort
  5. Relevance filter               — Groq → GPT → Claude fallback chain
  6. refine_with_claude             — dedup/normalize, Groq → GPT → Claude
"""

import os
import re
import json
from typing import List, Dict, Optional
from urllib.parse import urlparse

from services.groq_client import ask_groq

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

_anthropic_client = None

def _get_claude():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


# ── Country utilities ─────────────────────────────────────────

# ISO-2 country code → full name (common subset)
_ISO2_TO_NAME = {
    "AE": "UAE", "SA": "Saudi Arabia", "QA": "Qatar", "KW": "Kuwait",
    "OM": "Oman", "BH": "Bahrain", "IQ": "Iraq", "IR": "Iran",
    "IN": "India", "PK": "Pakistan", "TR": "Turkey", "EG": "Egypt",
    "JO": "Jordan", "GB": "United Kingdom", "DE": "Germany",
    "US": "United States", "CN": "China", "SG": "Singapore",
    "MY": "Malaysia", "KR": "South Korea", "JP": "Japan",
    "TM": "Turkmenistan", "KZ": "Kazakhstan", "AZ": "Azerbaijan",
    "UZ": "Uzbekistan", "TJ": "Tajikistan", "KG": "Kyrgyzstan",
    "GE": "Georgia", "AM": "Armenia", "RU": "Russia",
    "UA": "Ukraine", "BY": "Belarus", "LY": "Libya",
    "TN": "Tunisia", "MA": "Morocco", "DZ": "Algeria",
    "NG": "Nigeria", "ZA": "South Africa", "KE": "Kenya",
    "TZ": "Tanzania", "ET": "Ethiopia", "GH": "Ghana",
    "SN": "Senegal", "CI": "Ivory Coast",
    "FR": "France", "IT": "Italy", "ES": "Spain", "NL": "Netherlands",
    "BE": "Belgium", "PL": "Poland", "SE": "Sweden", "NO": "Norway",
    "AU": "Australia", "NZ": "New Zealand", "CA": "Canada",
    "BR": "Brazil", "MX": "Mexico", "AR": "Argentina",
    "TH": "Thailand", "VN": "Vietnam", "ID": "Indonesia",
    "PH": "Philippines", "BD": "Bangladesh", "LK": "Sri Lanka",
    "NP": "Nepal", "MM": "Myanmar", "KH": "Cambodia",
}

# Known country names to detect in address strings
_KNOWN_COUNTRIES = sorted([
    "afghanistan", "albania", "algeria", "angola", "argentina", "armenia",
    "australia", "austria", "azerbaijan", "bahrain", "bangladesh", "belarus",
    "belgium", "brazil", "bulgaria", "cambodia", "canada", "china",
    "colombia", "croatia", "czech republic", "denmark", "egypt", "ethiopia",
    "finland", "france", "georgia", "germany", "ghana", "greece",
    "hungary", "india", "indonesia", "iran", "iraq", "ireland", "israel",
    "italy", "ivory coast", "japan", "jordan", "kazakhstan", "kenya",
    "kuwait", "kyrgyzstan", "latvia", "lebanon", "libya", "lithuania",
    "malaysia", "mauritius", "mexico", "morocco", "mozambique", "myanmar",
    "nepal", "netherlands", "new zealand", "nigeria", "norway", "oman",
    "pakistan", "peru", "philippines", "poland", "portugal", "qatar",
    "romania", "russia", "saudi arabia", "senegal", "serbia", "singapore",
    "south africa", "south korea", "spain", "sri lanka", "sudan", "sweden",
    "switzerland", "syria", "taiwan", "tajikistan", "tanzania", "thailand",
    "tunisia", "turkey", "turkmenistan", "ukraine", "united arab emirates",
    "uae", "united kingdom", "united states", "uzbekistan", "venezuela",
    "vietnam", "yemen", "zambia", "zimbabwe",
], key=len, reverse=True)  # longest first so "saudi arabia" matches before "arabia"


def extract_country_from_delivery(delivery: str) -> str:
    """
    Extract just the country name from a full delivery address.

    Handles:
    - Simple country name:            "UAE"  → "UAE"
    - ISO-2 code in parens:           "Turkmenistan (TM)"  → "Turkmenistan"
    - Full address with ISO-2 at end: "9th km, Hazar, 745030, Turkmenistan (TM)"
    - Full address without code:      "9th km, Hazar, 745030, Turkmenistan"
    - Multiple countries (comma-sep): "UAE, Saudi Arabia"  → ["UAE", "Saudi Arabia"]
    """
    if not delivery:
        return "UAE"

    text = delivery.strip()

    # 1. ISO-2 code in parentheses anywhere in the string → look up full name
    iso_match = re.search(r'\(([A-Z]{2})\)', text)
    if iso_match:
        code = iso_match.group(1)
        if code in _ISO2_TO_NAME:
            return _ISO2_TO_NAME[code]

    # 2. Check if the whole string is a simple, short value (no commas or very few)
    #    If there's only one comma-segment that isn't a number / short code, use it
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) <= 2:
        # Treat the whole delivery as a country / country-pair
        return text

    # 3. Scan every token (longest countries first) for a known country name
    text_lower = text.lower()
    for country in _KNOWN_COUNTRIES:
        # Must be a word boundary match to avoid "iran" matching "ukraine"
        if re.search(r'\b' + re.escape(country) + r'\b', text_lower):
            # Return the properly-cased version from the original string if possible
            idx = text_lower.find(country)
            return text[idx: idx + len(country)]

    # 4. Fallback: last non-numeric, non-short segment
    for part in reversed(parts):
        if len(part) > 3 and not re.match(r'^[\d\s\-]+$', part):
            return part

    return text


# ── Quality Evaluation ───────────────────────────────────────

def _semantic_relevance_check(vendors: "List[Dict]", description: str, category: "Optional[str]") -> "Dict[str, float]":
    """
    Use Claude Sonnet (primary) → GPT-4o-mini (fallback) to semantically judge
    whether each vendor actually supplies what the RFQ needs.
    Returns {vendor_name: relevance_score 0.0–1.0}.
    Falls back to keyword heuristic if both LLMs fail.
    """
    if not vendors:
        return {}

    vendor_summaries = []
    for v in vendors:
        name = v.get("name") or v.get("vendor_name") or ""
        desc = v.get("description") or v.get("sourcing_rationale") or ""
        brands = v.get("brands") or ""
        vendor_summaries.append(f"- {name}: {desc} | brands: {brands}")

    vendor_block = "\n".join(vendor_summaries)
    item_context = description
    if category:
        item_context += f" (category: {category})"

    prompt = f"""You are a B2B procurement relevance checker.

RFQ item: {item_context}

Vendors to evaluate:
{vendor_block}

For each vendor, output a JSON object with the vendor name as key and a relevance score (0.0 to 1.0) as value.
Score 1.0 = clearly supplies this exact product type.
Score 0.5 = possibly relevant, overlapping industry.
Score 0.0 = unrelated / wrong industry.

Respond with ONLY valid JSON, no explanation. Example:
{{"Vendor A": 0.9, "Vendor B": 0.2}}"""

    raw = None

    # 1. Claude Sonnet — primary (best semantic understanding)
    try:
        if ANTHROPIC_API_KEY:
            import anthropic
            client = _get_claude()
            resp = client.messages.create(
                model      = "claude-sonnet-4-6",
                max_tokens = 512,
                messages   = [{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            print(f"  ✅ Claude semantic relevance check done")
    except Exception as e:
        print(f"  ⚠️  Claude relevance check failed ({e}) — trying GPT-4o-mini")

    # 2. GPT-4o-mini — fallback
    if not raw:
        try:
            import openai
            OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
            if OPENAI_API_KEY:
                client_oai = openai.OpenAI(api_key=OPENAI_API_KEY)
                resp = client_oai.chat.completions.create(
                    model      = "gpt-4o-mini",
                    max_tokens = 512,
                    messages   = [{"role": "user", "content": prompt}],
                )
                raw = resp.choices[0].message.content.strip()
                print(f"  ✅ GPT-4o-mini semantic relevance check done")
        except Exception as e:
            print(f"  ⚠️  GPT-4o-mini relevance check failed ({e}) — using keyword fallback")

    # Parse JSON response
    if raw:
        try:
            m = re.search(r'\{[^}]+\}', raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass

    # 3. Keyword heuristic fallback
    desc_words = set(description.lower().split())
    if category:
        desc_words |= set(category.lower().split())
    scores = {}
    for v in vendors:
        name = v.get("name") or v.get("vendor_name") or ""
        vendor_text = " ".join([name, v.get("description",""), v.get("sourcing_rationale",""), v.get("brands","")]).lower()
        hits = sum(1 for w in desc_words if len(w) > 3 and w in vendor_text)
        scores[name] = min(1.0, hits / max(1, len([w for w in desc_words if len(w) > 3])))
    return scores


def evaluate_quality(
    vendors:     "List[Dict]",
    description: str,
    category:    "Optional[str]" = None,
) -> "Dict":
    if not vendors:
        return {"count": 0, "avg_confidence": 0.0, "relevance_score": 0.0,
                "duplicate_ratio": 0.0, "trigger_web": True, "trigger_claude": False,
                "reasons": ["no vendors found"]}

    count      = len(vendors)
    raw_scores = [v.get("confidence_score") or v.get("score") or 5.0 for v in vendors]
    scores     = [s * 10 if s <= 1.0 else s for s in raw_scores]
    avg_conf   = sum(scores) / len(scores) if scores else 0.0

    # ── Semantic relevance via Claude → GPT (replaces keyword heuristic) ──
    sem_scores     = _semantic_relevance_check(vendors, description, category)
    sem_vals       = list(sem_scores.values())
    relevance_score = sum(sem_vals) / len(sem_vals) if sem_vals else 0.0

    # Tag each vendor with its semantic relevance score for downstream use
    for v in vendors:
        name = v.get("name") or v.get("vendor_name") or ""
        v["_semantic_relevance"] = sem_scores.get(name, 0.5)

    names   = [v.get("name", "").lower().strip() for v in vendors]
    domains = []
    for v in vendors:
        site = v.get("website") or v.get("link") or ""
        try:
            domain = urlparse(site).netloc.replace("www.", "")
            if domain:
                domains.append(domain.lower())
        except Exception:
            pass

    name_dupes      = len(names) - len(set(names))
    domain_dupes    = len(domains) - len(set(domains)) if domains else 0
    duplicate_ratio = (name_dupes + domain_dupes) / (count * 2) if count > 0 else 0.0

    reasons     = []
    trigger_web = False
    if count < 5:
        trigger_web = True; reasons.append(f"low count ({count})")
    if avg_conf < 6.0:
        trigger_web = True; reasons.append(f"low confidence ({avg_conf:.1f})/10")
    if relevance_score < 0.4:
        trigger_web = True; reasons.append(f"weak semantic relevance ({relevance_score:.2f})")

    return {
        "count":           count,
        "avg_confidence":  round(avg_conf, 2),
        "relevance_score": round(relevance_score, 2),
        "duplicate_ratio": round(duplicate_ratio, 2),
        "trigger_web":     trigger_web,
        "trigger_claude":  avg_conf < 6.0 or duplicate_ratio > 0.2,
        "reasons":         reasons,
        "semantic_scores": sem_scores,
    }


# ── 4a. OpenAI + Claude Vendor Discovery (primary) ───────────
# OpenAI and Claude know real industrial companies far better than Groq.
# Both return company name + official website so enrichment can crawl
# directly without a Sonar website-lookup call.

# Country alias groups — used to validate that returned vendors match the requested country.
# A vendor's reported country passes if it shares an alias group with the requested country.
_COUNTRY_ALIAS_GROUPS = [
    {"uae", "united arab emirates", "dubai", "abu dhabi", "sharjah", "ajman", "fujairah", "ras al khaimah"},
    {"saudi arabia", "ksa", "kingdom of saudi arabia", "riyadh", "jeddah", "makkah", "dammam"},
    {"qatar", "doha"},
    {"kuwait", "kuwait city"},
    {"oman", "muscat", "sultanate of oman"},
    {"bahrain", "manama"},
    {"iraq", "baghdad", "basra", "erbil"},
    {"iran", "tehran", "islamic republic of iran"},
    {"india", "mumbai", "delhi", "new delhi", "bangalore", "bengaluru", "chennai", "hyderabad", "pune", "ahmedabad"},
    {"pakistan", "karachi", "lahore", "islamabad"},
    {"uk", "united kingdom", "england", "britain", "london", "birmingham", "manchester"},
    {"usa", "united states", "united states of america", "america", "new york", "houston", "chicago"},
    {"germany", "deutschland", "berlin", "hamburg", "munich"},
    {"china", "prc", "people's republic of china", "beijing", "shanghai", "guangzhou", "shenzhen"},
    {"singapore", "sg"},
    {"malaysia", "kuala lumpur", "kl"},
    {"turkey", "türkiye", "istanbul", "ankara"},
    {"egypt", "cairo"},
    {"jordan", "amman"},
    {"turkmenistan", "tm", "ashgabat", "turkmen", "hazar", "balkanabat", "mary", "turkmenbashi"},
    {"kazakhstan", "kz", "almaty", "nur-sultan", "astana", "shymkent", "karaganda"},
    {"azerbaijan", "az", "baku"},
    {"uzbekistan", "uz", "tashkent", "samarkand"},
    {"georgia", "ge", "tbilisi"},
    {"russia", "russian federation", "moscow", "saint petersburg", "st. petersburg"},
    {"ukraine", "kyiv", "kiev"},
    {"nigeria", "lagos", "abuja"},
    {"south africa", "johannesburg", "cape town", "durban"},
    {"kenya", "nairobi"},
    {"ethiopia", "addis ababa"},
    {"ghana", "accra"},
    {"malaysia", "kuala lumpur", "kl"},
    {"indonesia", "jakarta", "surabaya"},
    {"thailand", "bangkok"},
    {"vietnam", "hanoi", "ho chi minh"},
    {"south korea", "korea", "seoul", "busan"},
    {"japan", "tokyo", "osaka"},
    {"australia", "sydney", "melbourne", "brisbane"},
    {"france", "paris", "lyon"},
    {"italy", "rome", "milan"},
    {"spain", "madrid", "barcelona"},
    {"netherlands", "amsterdam", "rotterdam"},
    {"belgium", "brussels"},
    {"poland", "warsaw"},
    {"sweden", "stockholm"},
    {"norway", "oslo"},
    {"switzerland", "zurich", "geneva"},
    {"canada", "toronto", "vancouver", "montreal"},
    {"brazil", "sao paulo", "rio de janeiro"},
    {"mexico", "mexico city", "monterrey"},
    {"morocco", "casablanca", "rabat"},
    {"algeria", "algiers"},
    {"tunisia", "tunis"},
    {"libya", "tripoli"},
    {"tanzania", "dar es salaam"},
    {"sri lanka", "colombo"},
    {"bangladesh", "dhaka"},
    {"nepal", "kathmandu"},
    {"philippines", "manila"},
]


def _country_matches(vendor_country: str, requested_country: str) -> bool:
    """True if vendor_country is the same region as requested_country."""
    vc = vendor_country.lower().strip()
    rc = requested_country.lower().strip()
    if not vc:
        return True  # Blank country — keep it; enrichment will verify
    if rc in vc or vc in rc:
        return True
    for group in _COUNTRY_ALIAS_GROUPS:
        in_vc = any(x in vc for x in group)
        in_rc = any(x in rc for x in group)
        if in_vc and in_rc:
            return True
    return False


def _discover_single_country(
    description:      "str",
    part_number:      "Optional[str]",
    brand:            "Optional[str]",
    channel_codes:    "List[str]",
    existing_vendors: "List[str]",
    country:          "str",
    extra:            "Optional[str]",
    target_count:     "int",
    start_from:       "str" = "openai-mini",
    channel_labels:   "Optional[str]" = None,
) -> "List[Dict]":
    """
    Single-country discovery via OpenAI gpt-4o-mini (or Claude Haiku fallback).
    Returns vendors WITH their official website URL so enrichment can crawl
    directly — no separate Sonar website-lookup needed.
    """
    from services.llm_router import ask_llm
    channels_str = channel_labels or (", ".join(channel_codes) if channel_codes else "OEM, LAD, IGS, OCD, B2B")
    exclude_list = (existing_vendors or [])[:40]
    exclude_str  = "\n".join(f"- {v}" for v in exclude_list) if exclude_list else "None"

    user_req_block = (
        f"SPECIAL USER REQUIREMENT (follow exactly):\n{extra}\n\n"
        if extra else ""
    )

    prompt = f"""You are a senior procurement specialist.

{user_req_block}MANDATORY COUNTRY CONSTRAINT: Every company you return MUST be physically located in {country.upper()} or have a registered branch/warehouse/office in {country.upper()}.
- Set the "country" field to the company's ACTUAL country (do not copy the requested country blindly)
- If a company is only in UAE and I asked for Saudi Arabia — DO NOT include it
- If you genuinely cannot find {target_count} real companies in {country}, return FEWER results — do NOT invent companies
- I will REJECT any company that is not actually based in or operating from {country}

PRODUCT TO SOURCE:
  Description : {description}
  Part Number : {part_number or 'N/A'}
  Brand       : {brand or 'N/A'}
  Channels    : {channels_str}

DO NOT REPEAT THESE COMPANIES:
{exclude_str}

OTHER RULES:
- Only companies that DEFINITELY EXIST with a real, working website you know
- Include the company's official website URL for every entry
- Only B2B industrial suppliers, distributors, authorized dealers, trading companies
- No B2C: Amazon, Noon, Alibaba, Souq, eBay
- Confidence score 6+ only

Return a JSON object with a "vendors" key:
{{"vendors": [
  {{
    "name": "Full Company Name",
    "website": "https://actual-company-website.com",
    "country": "ACTUAL country where this company is physically located",
    "city": "City in {country}",
    "brands": "specific brands they carry",
    "channel_code": "LAD",
    "confidence_score": 8.0,
    "sourcing_rationale": "why they supply this specific item",
    "description": "what this company does",
    "source": "ai_discovery"
  }}
]}}"""

    try:
        raw    = ask_llm(prompt, json_mode=True, max_tokens=1500, start_from=start_from)
        clean  = re.sub(r"```json|```", "", raw).strip()
        # Attempt JSON parse with truncation recovery
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            # Truncated JSON — try to recover completed vendor objects
            last_complete = clean.rfind("},")
            if last_complete > 0:
                try:
                    parsed = json.loads(clean[:last_complete+1] + "]}")
                except Exception:
                    try:
                        parsed = json.loads(clean[:last_complete+1] + "]")
                    except Exception:
                        print(f"  [{start_from}] [{country}] JSON recovery failed")
                        return []
            else:
                print(f"  [{start_from}] [{country}] JSON parse failed: {clean[:100]}")
                return []
        vendors = parsed.get("vendors", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(vendors, list):
            return []

        valid = []
        for v in vendors:
            v_country = (v.get("country") or "").strip()
            # Filter out vendors clearly from the wrong country
            if v_country and not _country_matches(v_country, country):
                print(f"    ⚠️  Dropped '{v.get('name','?')}' — wrong country: '{v_country}' ≠ '{country}'")
                continue
            # Only set country when the LLM left it blank
            if not v_country:
                v["country"] = country
            v["source"] = "ai_discovery"
            site = (v.get("website") or "").strip()
            if site and not site.startswith("http"):
                v["website"] = "https://" + site
            valid.append(v)

        print(f"  [{start_from}] [{country}]: {len(valid)} valid (of {len(vendors)} returned)")
        return valid
    except Exception as e:
        print(f"  [{start_from}] [{country}] error: {e}")
        return []


def openai_claude_discover_vendors(
    description:       "str",
    part_number:       "Optional[str]"  = None,
    brand:             "Optional[str]"  = None,
    channel_codes:     "List[str]"      = None,
    channel_labels:    "str"            = None,
    existing_vendors:  "List[str]"      = None,
    existing_websites: "List[str]"      = None,
    delivery:          "Optional[str]"  = None,
    extra:             "Optional[str]"  = None,
    target_count:      "int"            = 30,
) -> "List[Dict]":
    """
    LLM-based vendor discovery per country:
      Phase 1 — GPT-4o-mini  (best knowledge of real companies)
      Phase 2 — Claude Haiku  (if GPT found < target)
      Phase 3 — Groq          (last-resort LLM, if still < 3)
      Phase 4 — Sonar         (paid live-web, absolute last resort)
    """
    country_list = [c.strip() for c in extract_country_from_delivery(delivery or "UAE").split(",") if c.strip()] or ["UAE"]
    per_country  = max(5, target_count // len(country_list))

    def _norm(name: str) -> str:
        cleaned = re.sub(r"[^\w\s]", "", name.lower().strip())
        cleaned = re.sub(
            r"\b(llc|ltd|inc|co|fze|fzc|wll|saog|spc|llp|pvt|private|limited|group|trading|industries|international|enterprise|enterprises|solutions|services|supply|supplies|corporation|corp|company|gmbh|bv|ag|sa|pty)\b",
            "", cleaned
        )
        return re.sub(r"\s+", " ", cleaned).strip()

    seen_norm   = {_norm(v) for v in (existing_vendors or [])}
    all_vendors: "List[Dict]" = []
    effective_channels = channel_labels or (", ".join(channel_codes) if channel_codes else None)

    for country in country_list:
        exclude_so_far = list(existing_vendors or []) + [v["name"] for v in all_vendors]

        # ── Phase 1: GPT-4o-mini — best real-company knowledge ──
        batch = _discover_single_country(
            description, part_number, brand, channel_codes,
            exclude_so_far, country, extra, per_country,
            start_from="openai-mini",
            channel_labels=effective_channels,
        )
        print(f"  [Phase 1/GPT] [{country}]: {len(batch)} vendors")

        # ── Phase 2: Claude Haiku if GPT found fewer than target ──
        if len(batch) < per_country:
            haiku_batch = _discover_single_country(
                description, part_number, brand, channel_codes,
                exclude_so_far + [v["name"] for v in batch],
                country, extra, per_country - len(batch),
                start_from="anthropic-haiku",
                channel_labels=effective_channels,
            )
            print(f"  [Phase 2/Claude] [{country}]: {len(haiku_batch)} additional")
            batch.extend(haiku_batch)

        # ── Phase 3: Sonar if still < 3 ──
        if len(batch) < 3:
            print(f"  [Phase 3/Sonar] [{country}]: AI found only {len(batch)} — trying Sonar live search...")
            try:
                from services.sonar_discovery import sonar_country_discover
                sonar_batch = sonar_country_discover(
                    description=description,
                    country=country,
                    extra=extra,
                    existing_names=exclude_so_far + [v["name"] for v in batch],
                    target_count=per_country,
                )
                print(f"  [Phase 3/Sonar] [{country}]: {len(sonar_batch)} additional")
                batch.extend(sonar_batch)
            except Exception as e:
                print(f"  ⚠️  Sonar fallback error: {e}")

        for v in batch:
            norm = _norm(v.get("name", ""))
            if not norm or norm in seen_norm:
                continue
            seen_norm.add(norm)
            all_vendors.append(v)

    print(f"  discover_vendors total: {len(all_vendors)} across {len(country_list)} countries")
    return all_vendors


# ── 4a-legacy. Groq Vendor Discovery (fallback only) ─────────
# Kept as emergency fallback when both OpenAI and Claude are unavailable.

def _groq_single_country(
    description:      str,
    part_number:      "Optional[str]",
    brand:            "Optional[str]",
    channel_codes:    "List[str]",
    existing_vendors: "List[str]",
    country:          str,
    extra:            "Optional[str]",
    target_count:     int,
    channel_labels:   "Optional[str]" = None,
) -> "List[Dict]":
    """Single Groq call for ONE country only. Called once per selected country."""
    channels_str = channel_labels or (", ".join(channel_codes) if channel_codes else "LAD, OEM, IGS, OCD, ISD, B2B")
    exclude_str  = "\n".join(f"- {v}" for v in (existing_vendors or [])[:40]) or "None"
    prompt_block = f"\nSPECIAL INSTRUCTIONS (MUST FOLLOW):\n{extra}" if extra else ""

    prompt = f"""Find {target_count} real B2B suppliers in {country.upper()} for: {description[:80]}
Part: {part_number or 'N/A'} | Brand: {brand or 'N/A'}
{prompt_block}
Channels: {channels_str}
Skip: {exclude_str[:300]}
Rules: only companies IN {country}, no B2C, confidence 7+, no website/email/phone fields.
JSON array: [{{"name":"...","country":"{country}","city":"...","brands":"...","channel_code":"LAD","confidence_score":8.0,"sourcing_rationale":"...","source":"groq_sourcing"}}]"""

    try:
        raw   = ask_groq(prompt, json_mode=False, max_tokens=800)
        clean = re.sub(r"```json|```", "", raw).strip()
        try:
            result = json.loads(clean)
        except json.JSONDecodeError:
            last   = clean.rfind('},')
            result = json.loads(clean[:last+1] + ']') if last > 0 else []
        vendors = result if isinstance(result, list) else []
        # Force country field to match requested country
        for v in vendors:
            v["country"] = country
        print(f"  🌍 Groq [{country}]: {len(vendors)} vendors")
        return vendors
    except Exception as e:
        print(f"  ⚠️  Groq [{country}] error: {e}")
        return []


def groq_discover_vendors(
    description:       str,
    part_number:       "Optional[str]"  = None,
    brand:             "Optional[str]"  = None,
    channel_codes:     "List[str]"      = None,
    channel_labels:    "Optional[str]"  = None,
    existing_vendors:  "List[str]"      = None,
    existing_websites: "List[str]"      = None,  # accepted but ignored (no web search)
    delivery:          "Optional[str]"  = None,
    extra:             "Optional[str]"  = None,
    target_count:      int              = 35,
) -> "List[Dict]":
    """
    Calls Groq once per selected country to guarantee country diversity.
    Each call is focused on ONE country — much more reliable than asking
    for all countries in a single prompt (which always defaults to UAE).
    Memory-light: sequential calls, small max_tokens each.
    """
    country_list = [c.strip() for c in extract_country_from_delivery(delivery or "UAE").split(",") if c.strip()] or ["UAE"]
    per_country  = max(6, target_count // len(country_list))

    def _norm(name: str) -> str:
        cleaned = re.sub(r"[^\w\s]", "", name.lower().strip())
        cleaned = re.sub(
            r"\b(llc|ltd|inc|co|fze|fzc|wll|saog|spc|llp|pvt|private|limited|group|trading|industries|international|enterprise|enterprises|solutions|services|supply|supplies|corporation|corp|company|gmbh|bv|ag|sa|pty)\b",
            "", cleaned
        )
        return re.sub(r"\s+", " ", cleaned).strip()

    seen_norm    = {_norm(v) for v in (existing_vendors or [])}
    all_vendors  = []

    for country in country_list:
        # Pass all already-found names so Groq doesn't repeat across countries
        exclude_for_call = list(existing_vendors or []) + [v["name"] for v in all_vendors]
        batch = _groq_single_country(
            description, part_number, brand, channel_codes,
            exclude_for_call, country, extra, per_country,
            channel_labels=channel_labels,
        )
        for v in batch:
            norm = _norm(v.get("name", ""))
            if not norm or norm in seen_norm:
                continue
            seen_norm.add(norm)
            all_vendors.append(v)

    print(f"  ✅ groq_discover_vendors total: {len(all_vendors)} across {len(country_list)} countries")
    return all_vendors


# ── 4b. Claude Haiku Relevance Filter (replaces Groq) ────────
# Haiku is far better at nuanced product-category matching than Groq,
# and costs ~10× less than Claude Sonnet. Input ~$0.00025/1k, output ~$0.00125/1k.

def groq_relevance_filter(
    vendors:     "List[Dict]",
    description: str,
    part_number: "Optional[str]" = None,
    brand:       "Optional[str]" = None,
    threshold:   int = 6,
) -> "List[Dict]":
    """
    Relevance filter: Groq first → GPT-4o-mini → Claude Haiku.
    Uses compact prompt to stay within Azure B1 memory limits.
    """
    if not vendors:
        return vendors

    # Compact rows — only what the LLM needs for scoring (saves tokens & memory)
    rows = [{"i": i, "n": v.get("name","")[:60], "b": (v.get("brands","") or "")[:40],
             "r": (v.get("sourcing_rationale","") or "")[:60]}
            for i, v in enumerate(vendors)]
    part_str  = f" | Part: {part_number}" if part_number else ""
    brand_str = f" | Brand: {brand}" if brand else ""
    prompt = f"""Score each vendor's relevance (0-10) for: {description[:80]}{part_str}{brand_str}
9-10=exact product, 7-8=strong match, 5-6=generic trader, <5=irrelevant.
VENDORS: {json.dumps(rows)}
Return JSON only: [{{"i":0,"s":8}}]"""

    # Try Groq first
    raw = None
    try:
        raw = ask_groq(prompt, json_mode=False, max_tokens=400)
        print("  ✅ Relevance filter: Groq succeeded")
    except Exception as e:
        print(f"  ⚠️  Groq relevance filter failed: {e} — trying GPT/Claude via router")
        try:
            from services.llm_router import ask_llm
            raw = ask_llm(prompt, json_mode=False, max_tokens=400, start_from="openai-mini")
        except Exception as e2:
            print(f"  ⚠️  Router also failed: {e2} — returning unfiltered")
            return vendors

    try:
        clean  = re.sub(r"```json|```", "", raw).strip()
        scores = json.loads(clean)
        if not isinstance(scores, list):
            return vendors
        score_map  = {e["i"]: e["s"] for e in scores if "i" in e and "s" in e}
        filtered, dropped = [], 0
        for i, v in enumerate(vendors):
            s = score_map.get(i, 5)
            if s >= threshold:
                v["relevance_score"] = s; filtered.append(v)
            else:
                dropped += 1; print(f"  ✂️  Dropped ({s}/10): {v.get('name','?')}")
        print(f"  ✅ Relevance filter: {len(filtered)} kept, {dropped} dropped (threshold {threshold}/10)")
        return filtered
    except Exception as e:
        print(f"  ⚠️  Relevance filter parse error: {e} — returning unfiltered")
        return vendors


def _haiku_relevance_filter(
    vendors:     "List[Dict]",
    description: str,
    part_number: "Optional[str]" = None,
    brand:       "Optional[str]" = None,
    threshold:   int = 6,
) -> "List[Dict]":
    """Claude Haiku relevance filter — better than Groq at product-category nuance."""
    rows = [
        {"i": i, "name": v.get("name",""), "brands": v.get("brands",""),
         "rationale": v.get("sourcing_rationale","")[:80]}
        for i, v in enumerate(vendors)
    ]
    part_str  = f" | Part: {part_number}" if part_number else ""
    brand_str = f" | Brand: {brand}" if brand else ""

    prompt = f"""Score each vendor's relevance (0-10) for procuring:
{description[:100]}{part_str}{brand_str}

9-10 = sells this exact product/category
7-8  = very likely stocks it
5-6  = generic industrial trader, unclear product fit
<5   = wrong category or irrelevant

VENDORS:
{json.dumps(rows)}

Return JSON array only: [{{"i":0,"s":9,"r":"one-line reason"}}]"""

    try:
        client = _get_claude()
        resp   = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw    = resp.content[0].text.strip()
        clean  = re.sub(r"```json|```", "", raw).strip()
        scores = json.loads(clean)
        if not isinstance(scores, list):
            return vendors
        score_map  = {e["i"]: e for e in scores if "i" in e}
        filtered, dropped = [], 0
        for i, v in enumerate(vendors):
            entry = score_map.get(i, {})
            s = entry.get("s", 5)
            if s >= threshold:
                v["relevance_score"]  = s
                v["relevance_reason"] = entry.get("r", "")
                filtered.append(v)
            else:
                dropped += 1
                print(f"  ✂️  Dropped ({s}/10): {v.get('name','?')} — {entry.get('r','')}")
        print(f"  ✅ Haiku relevance filter: {len(filtered)} kept, {dropped} dropped (threshold {threshold}/10)")
        return filtered
    except Exception as e:
        print(f"  ⚠️  Haiku relevance filter error: {e} — returning unfiltered")
        return vendors


# ── 4c. Claude Relevance Filter (fallback only) ───────────────

def claude_relevance_filter(
    vendors:     "List[Dict]",
    description: str,
    part_number: "Optional[str]" = None,
    brand:       "Optional[str]" = None,
    threshold:   int = 6,
) -> "List[Dict]":
    """
    Uses Claude to score each vendor's relevance to the specific item.
    Vendors scoring below threshold (default 6/10) are dropped.

    Runs AFTER discovery and BEFORE contact enrichment so Sonar/crawl
    credits are not wasted on vendors that won't make the final list.
    """
    if not vendors:
        return vendors

    if not ANTHROPIC_API_KEY:
        print("  ⚠️  ANTHROPIC_API_KEY not set — skipping relevance filter")
        return vendors

    # Cap to 20 vendors — avoids large payloads on Azure B1
    vendors = vendors[:20]
    vendor_summaries = [
        {"i": i, "n": v.get("name","")[:60], "b": (v.get("brands","") or "")[:40],
         "r": (v.get("sourcing_rationale","") or "")[:60]}
        for i, v in enumerate(vendors)
    ]

    part_str  = f" | Part: {part_number}" if part_number else ""
    brand_str = f" | Brand: {brand}" if brand else ""

    prompt = f"""Score each vendor's relevance (0-10) for: {description[:100]}{part_str}{brand_str}
9-10=exact product match, 7-8=strong match, 5-6=generic trader, <5=irrelevant/wrong category.
Be strict — fewer accurate results is better than many irrelevant ones.

VENDORS: {json.dumps(vendor_summaries)}

Return JSON only: [{{"index":0,"relevance_score":8,"relevance_reason":"one line"}}]"""

    # Try Groq → GPT → Claude via router (same chain as discovery)
    raw = None
    try:
        raw = ask_groq(prompt, json_mode=False, max_tokens=600)
        print("  ✅ Claude relevance filter: Groq succeeded")
    except Exception as e:
        print(f"  ⚠️  Groq failed in relevance filter: {e} — trying router (GPT→Claude)")
        try:
            from services.llm_router import ask_llm
            raw = ask_llm(prompt, json_mode=False, max_tokens=600, start_from="openai-mini")
        except Exception as e2:
            print(f"  ⚠️  All LLMs failed in relevance filter: {e2} — returning unfiltered")
            return vendors

    try:
        clean  = re.sub(r"```json|```", "", raw).strip()
        scores = json.loads(clean)

        if not isinstance(scores, list):
            print("  ⚠️  Relevance filter returned non-list — skipping filter")
            return vendors

        score_map = {entry.get("index", entry.get("i")): entry for entry in scores
                     if "index" in entry or "i" in entry}
        filtered  = []
        dropped   = 0

        for i, vendor in enumerate(vendors):
            score_entry = score_map.get(i)
            if score_entry is None:
                vendor["relevance_score"]  = 5
                vendor["relevance_reason"] = "Not scored — kept by default"
                filtered.append(vendor)
                continue

            rel_score = score_entry.get("relevance_score", score_entry.get("s", 5))
            if rel_score >= threshold:
                vendor["relevance_score"]  = rel_score
                vendor["relevance_reason"] = score_entry.get("relevance_reason", score_entry.get("r", ""))
                filtered.append(vendor)
            else:
                dropped += 1
                print(f"  ✂️  Dropped ({rel_score}/10): {vendor.get('name','?')} — {score_entry.get('relevance_reason','')}")

        print(f"  ✅ Relevance filter (claude path): {len(filtered)} kept, {dropped} dropped (threshold {threshold}/10)")
        return filtered

    except Exception as e:
        print(f"  ⚠️  Relevance filter parse error: {e} — returning unfiltered list")
        return vendors


# ── 5. Claude Validation + Cleaning ──────────────────────────

def refine_with_claude(
    vendors:     "List[Dict]",
    description: str,
    extra:       "Optional[str]" = None,
) -> "List[Dict]":
    """
    Validates, deduplicates, normalizes and ranks suppliers.
    Only called when quality gate triggers.
    """
    if not vendors:
        return vendors

    # Cap to 15 — avoids large payloads on Azure B1 (1.75 GB RAM)
    vendors = vendors[:15]
    # Compact representation — only fields needed for dedup/rank
    slim = [{"name": v.get("name","")[:60], "country": v.get("country",""),
             "city": v.get("city",""), "website": v.get("website",""),
             "channel_code": v.get("channel_code",""),
             "confidence_score": v.get("confidence_score", 5.0),
             "source": v.get("source","")}
            for v in vendors]

    prompt_block = f"\nSPECIAL INSTRUCTIONS: {extra}" if extra else ""
    prompt = f"""Validate this supplier list for: {description[:100]}{prompt_block}
Tasks: remove irrelevant/duplicate companies, normalize names/countries, prefer OEM>distributor>trader, keep max 15.
VENDORS: {json.dumps(slim)}
Return JSON array only (same fields):
[{{"name":"...","country":"...","city":"...","website":"...","channel_code":"...","confidence_score":7.0,"source":"refined"}}]"""

    # Groq first → GPT → Claude
    raw = None
    try:
        raw = ask_groq(prompt, json_mode=False, max_tokens=1000)
        print("  ✅ refine_with_claude: Groq succeeded")
    except Exception as e:
        print(f"  ⚠️  Groq failed in refinement: {e} — trying GPT/Claude via router")
        try:
            from services.llm_router import ask_llm
            raw = ask_llm(prompt, json_mode=False, max_tokens=1000, start_from="openai-mini")
        except Exception as e2:
            print(f"  ⚠️  Refinement all LLMs failed: {e2} — returning original vendors")
            return vendors

    try:
        clean  = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(clean)
        print(f"  🤖 Refined: {len(vendors)} → {len(result)} vendors")
        return result if isinstance(result, list) else vendors
    except Exception as e:
        print(f"  ⚠️  Refinement parse error: {e} — returning original vendors")
        return vendors


# ── 6. Domain extraction utility ─────────────────────────────

def extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "").lower()
    except Exception:
        return ""


# ── 7. Merge vendor lists ─────────────────────────────────────

def merge_vendor_lists(
    groq_vendors: "List[Dict]",
    web_vendors:  "List[Dict]",
) -> "List[Dict]":
    existing_names   = {v.get("name", "").lower().strip() for v in groq_vendors}
    existing_domains = {
        extract_domain(v.get("website") or v.get("link") or "")
        for v in groq_vendors if v.get("website") or v.get("link")
    }

    merged = list(groq_vendors)

    for v in web_vendors:
        name   = v.get("name", "").lower().strip()
        domain = extract_domain(v.get("website") or "")
        if name in existing_names:
            continue
        if domain and domain in existing_domains:
            continue
        v["source"] = v.get("source") or "web_groq"
        merged.append(v)
        existing_names.add(name)
        if domain:
            existing_domains.add(domain)

    print(f"  🔀 Merged: {len(groq_vendors)} Groq + {len(web_vendors)} web = {len(merged)} total")
    return merged