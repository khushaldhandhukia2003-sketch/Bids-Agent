"""
services/contact_enrichment.py

Contact enrichment pipeline. Per vendor:
  1. Perplexity Sonar (paid, live web)  → website + email + phone
     Fallback when Sonar is exhausted   → Claude / Groq LLM guess
  2. BeautifulSoup crawl                → scrape real email from contact page
  3. Crawled email preferred over Sonar suggestion
  4. MX/DNS verify via dnspython        → drop undeliverable addresses

Azure B2 safe: ~9s per vendor × 18 max ≈ 162s < 230s hard limit.
"""

import os
import re
import time
import json
import requests
from services.email_verifier import filter_valid_emails
from datetime import date
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Set

# ── Config ────────────────────────────────────────────────────

SONAR_API_KEY   = os.getenv("PERPLEXITY_API_KEY", "")
CRAWL_TIMEOUT   = 8    # 8s max per crawl request — enough for slow Gulf region sites
CRAWL_DELAY     = 0.3  # small pause between vendors to avoid hammering APIs

CONFIDENCE_BY_METHOD = {
    "crawl_direct":        0.95,
    "crawl_sonar":         0.90,
    "sonar_only":          0.60,
    "replaced":            0.85,
    "replaced_sonar_only": 0.55,
    "manual_required":     0.00,
    "manufacturer_direct": 0.98,
}

LEGACY_EMAIL_DOMAINS = {
    "emirates.net.ae", "eim.ae", "etisalat.net.ae",
    "du.ae", "hotmail.com", "yahoo.com", "gmail.com",
}

# Directory / listing sites — never real company websites; clear them before enrichment
JUNK_DIRECTORY_DOMAINS = {
    "fyind.com", "yellowpages.ae", "yellowpages.com", "yelp.com",
    "bizdirectory.ae", "uaeyellowpages.com", "gulfjobs.com",
    "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
    "justdial.com", "indiamart.com", "tradeindia.com", "alibaba.com",
    "thomasnet.com", "kompass.com", "europages.com", "b2blistings.org",
    "dnb.com", "manta.com", "zoominfo.com", "chamberofcommerce.com",
}

# Fix 5: Gulf/Middle East countries — alternatives should be from here
GULF_COUNTRIES = {
    "uae", "united arab emirates", "qatar", "saudi arabia", "ksa",
    "kuwait", "oman", "bahrain", "jordan", "egypt", "turkey",
    "india",   # common source for Gulf industrial suppliers
    "global",  # manufacturer entries
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

CONTACT_PAGE_PATHS = [
    "/contact", "/contact-us", "/contacts",
    "/about",   "/about-us",
    "/",
]

PREFERRED_EMAIL_PREFIXES = [
    "info", "sales", "enquir", "commercial", "contact",
    "trade", "supply", "purchase", "procurement",
    "middleeast", "uae", "dubai", "gulf",
]

DEPRIORITIZED_EMAIL_PREFIXES = [
    "webmaster", "noreply", "no-reply", "admin",
    "marketing", "pr", "media", "press",
]


# ── Claude Haiku website validation ──────────────────────────

def _website_is_reachable(url: str, timeout: int = 8) -> bool:
    """
    Check if a website is reachable. Tries HEAD first (fast); falls back to
    GET if the server returns 405 or blocks HEAD (common on .ae/.sa sites).
    Also tries www. prefix and http:// fallback variants.
    """
    cleaned = _clean_url(url)
    if not cleaned:
        return False
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    }

    def _try_one(attempt_url: str) -> bool:
        try:
            resp = requests.head(attempt_url, timeout=timeout, allow_redirects=True, headers=hdrs)
            if resp.status_code < 400:
                return True
            if resp.status_code in (405, 403, 503):
                resp2 = requests.get(attempt_url, timeout=timeout, allow_redirects=True,
                                     headers=hdrs, stream=True)
                resp2.close()
                return resp2.status_code < 400
        except Exception:
            pass
        return False

    # Build list of variants to try: https, http, and www. prefix if missing
    variants = [cleaned]
    http_ver = cleaned.replace("https://", "http://", 1)
    if http_ver != cleaned:
        variants.append(http_ver)
    # Add www. variant if not already present
    for v in list(variants):
        from urllib.parse import urlparse as _up
        parsed = _up(v)
        if parsed.netloc and not parsed.netloc.startswith("www."):
            variants.append(v.replace(parsed.netloc, "www." + parsed.netloc, 1))

    for attempt_url in variants:
        if _try_one(attempt_url):
            return True
    return False




def _claude_verify_website(
    name:        str,
    country:     str,
    description: str,
    bad_url:     str,
) -> Optional[str]:
    """
    Find the correct official website: Groq first → GPT → Claude Haiku.
    """
    prompt = (
        f"What is the official website for B2B industrial supplier:\n"
        f"Company: {name} | Country: {country} | Product: {description[:60]}\n"
        f"Previously tried (not working): {bad_url}\n"
        f"Reply with ONLY the URL (e.g. https://www.company.ae) or NOT_FOUND."
    )

    def _try_url(raw: str) -> Optional[str]:
        result = (raw or "").strip().split()[0]
        if not result or result.upper() == "NOT_FOUND" or not result.startswith("http"):
            return None
        if _website_is_reachable(result):
            return _clean_url(result)
        return None

    # Groq first
    try:
        from services.groq_client import ask_groq
        raw = ask_groq(prompt, json_mode=False, max_tokens=80)
        url = _try_url(raw)
        if url:
            print(f"      ✅ Groq found correct website: {url}")
            return url
    except Exception as e:
        print(f"      ⚠️  Groq website verify error: {e}")

    # GPT fallback
    try:
        from services.llm_router import ask_llm
        raw = ask_llm(prompt, json_mode=False, max_tokens=80, start_from="openai-mini")
        url = _try_url(raw)
        if url:
            print(f"      ✅ GPT found correct website: {url}")
            return url
    except Exception as e:
        print(f"      ⚠️  GPT website verify error: {e}")

    # Claude Haiku last resort
    try:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if api_key:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp   = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            url = _try_url(resp.content[0].text)
            if url:
                print(f"      ✅ Claude Haiku found correct website: {url}")
                return url
    except Exception as e:
        print(f"      ⚠️  Claude website verify error: {e}")

    return None


# ── Verification metadata ─────────────────────────────────────

def _build_verification_metadata(
    contact_source: str,
    email:          str,
    phone:          str,
    manual_lookup:  bool = False,
    legacy_domain:  bool = False,
    phone_missing:  bool = False,
) -> Dict:
    confidence    = CONFIDENCE_BY_METHOD.get(contact_source, 0.5)
    notes         = []
    manual_review = manual_lookup

    if legacy_domain:
        confidence    = min(confidence, 0.5)
        manual_review = True
        notes.append("Legacy email domain suspected — verify this address is still active")
    if contact_source == "sonar_only":
        notes.append("Contact details from Sonar only — not independently verified by crawl")
    if phone_missing:
        manual_review = True
        notes.append("Phone number could not be found — manual lookup recommended")
    if manual_lookup:
        notes.append("Auto-verification failed — contacts require manual lookup")

    return {
        "verification_method":     contact_source,
        "verification_confidence": round(confidence, 2),
        "last_verified_date":      date.today().isoformat(),
        "manual_review_required":  manual_review,
        "verification_notes":      " | ".join(notes) if notes else "OK",
    }


def _is_legacy_domain(email: str) -> bool:
    if not email or "@" not in email:
        return False
    return email.split("@")[1].lower() in LEGACY_EMAIL_DOMAINS


# ── Fix 4: Relaxed email domain matching ─────────────────────

def _normalize_domain_for_match(domain: str) -> str:
    """
    Strips city/region prefixes from domains for flexible matching.
    giscoauh.ae → gisco.ae
    dxb.company.com → company.com
    uae.brand.com → brand.com
    """
    domain = re.sub(r"^www\.", "", domain.lower().strip())
    # Strip 2-3 letter city/country prefixes at start of domain
    # e.g. auh, dxb, shj, uae, ksa, me
    domain = re.sub(r"^(auh|dxb|shj|uae|ksa|me|gcc|mena)\.", "", domain)
    # Strip them as suffix of the first label
    # e.g. giscoauh.ae → gisco.ae
    parts = domain.split(".")
    if parts:
        parts[0] = re.sub(r"(auh|dxb|shj|uae|ksa|me)$", "", parts[0])
        if not parts[0]:   # if stripping left it empty, restore
            parts[0] = domain.split(".")[0]
    return ".".join(parts)


def _email_matches_domain(email: str, website_domain: str) -> bool:
    """
    Fix 4: Relaxed domain matching — strips city prefixes before comparing.
    gisco@giscoauh.ae vs gisco.ae → True (city prefix stripped)
    info@henrilorenzi.com vs alameenind.com → False (clearly different)
    """
    if not email or "@" not in email or not website_domain:
        return True   # can't check — let it through
    email_domain = _normalize_domain_for_match(email.split("@")[1])
    site_domain  = _normalize_domain_for_match(website_domain)
    # Exact match or one is subdomain of the other
    return (email_domain == site_domain or
            email_domain.endswith("." + site_domain) or
            site_domain.endswith("." + email_domain))


# ── Fuzzy deduplication ───────────────────────────────────────

def _normalize_company_name(name: str) -> str:
    if not name:
        return ""
    n = name.lower().strip()
    suffixes = [
        r"\bllc\b", r"\bl\.l\.c\b", r"\bltd\b", r"\blimited\b",
        r"\binc\b", r"\bcorp\b", r"\bco\b", r"\bcompany\b",
        r"\bgroup\b", r"\bholding\b", r"\bholdings\b",
        r"\bindustries\b", r"\bindustry\b", r"\btrading\b",
        r"\bmanufacturing\b", r"\benterprises\b", r"\benterprise\b",
        r"\bsaog\b", r"\bsaoc\b", r"\bfzc\b", r"\bfze\b",
        r"\b\(.*?\)\b",
    ]
    for suffix in suffixes:
        n = re.sub(suffix, "", n)
    n = re.sub(r"[^\w\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def deduplicate_vendors(vendors: List[Dict]) -> List[Dict]:
    seen    = {}
    result  = []
    dropped = 0
    for vendor in vendors:
        norm = _normalize_company_name(vendor.get("name", ""))
        if not norm:
            result.append(vendor)
            continue
        if norm in seen:
            existing_idx   = seen[norm]
            existing_score = result[existing_idx].get("confidence_score") or 0
            this_score     = vendor.get("confidence_score") or 0
            if this_score > existing_score:
                result[existing_idx] = vendor
                seen[norm]           = existing_idx
            dropped += 1
            print(f"  🔁 Dedup: '{vendor.get('name')}' matches existing — dropped")
        else:
            seen[norm] = len(result)
            result.append(vendor)
    if dropped > 0:
        print(f"  ✅ Deduplication: {len(vendors)} → {len(result)} vendors ({dropped} removed)")
    return result


# ── Main entry point ──────────────────────────────────────────

def enrich_vendor_contacts(
    vendors:        List[Dict],
    description:    str,
    country:        str = "UAE",
    search_id:      str = None,
    progress_store: dict = None,
) -> List[Dict]:
    """
    Enriches each vendor with real contact details.
    Per vendor: 1 Sonar call (live web) + 1 contact-page crawl + MX verify.
    """
    if not vendors:
        return vendors

    vendors = deduplicate_vendors(vendors)

    def _log(msg: str):
        print(msg)
        if search_id and progress_store is not None and search_id in progress_store:
            progress_store[search_id]["log"].append(msg)

    _log(f"\n  Contact enrichment: {len(vendors)} vendors (parallel)")

    # Initialise vendor rows in progress store
    rows_store = None
    if search_id and progress_store is not None and search_id in progress_store:
        progress_store[search_id]["vendors"] = [
            {"name": v.get("name",""), "status": "queued", "website": v.get("website",""), "source": v.get("source",""), "email": ""}
            for v in vendors
        ]
        rows_store = progress_store[search_id]["vendors"]

    results_by_idx = {}

    def _process(args):
        i, vendor = args
        name = vendor.get("name", "Unknown")
        _log(f"\n  [{i+1}/{len(vendors)}] {name}")
        if rows_store is not None and i < len(rows_store):
            rows_store[i]["status"] = "searching"

        result = _enrich_single(vendor, description, country)

        if result.get("verified") or result.get("manual_lookup"):
            status  = "verified" if result.get("verified") else "manual"
            method  = result.get("verification_method", "")
            website = result.get("website", "")
            emails_found = result.get("emails") or ([result["email"]] if result.get("email") else [])
            if result.get("verified"):
                _log(f"    OK {method} | emails: {emails_found or '-'} | phone: {result.get('phone') or '-'}")
            else:
                _log(f"    MANUAL: {result.get('verification_notes')}")
        else:
            status  = "dropped"
            method  = result.get("drop_reason", "")
            website = result.get("website", "")
            emails_found = []
            _log(f"    DROPPED: {method}")

        if rows_store is not None and i < len(rows_store):
            rows_store[i].update({
                "status":  status,
                "website": website,
                "source":  method,
                "email":   ", ".join(emails_found) if emails_found else "",
            })

        results_by_idx[i] = result if (result.get("verified") or result.get("manual_lookup")) else None

        # Auto-blacklisting disabled — user manages restricted companies manually

    from concurrent.futures import ThreadPoolExecutor, as_completed
    # 2 workers: B1-safe (1 core, 1.75GB RAM — 3 workers causes memory spikes)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_process, (i, v)) for i, v in enumerate(vendors)]
        for f in as_completed(futures):
            f.result()  # re-raise any exception

    # Preserve original order
    enriched = [results_by_idx[i] for i in range(len(vendors)) if results_by_idx.get(i) is not None]

    verified_count = sum(1 for v in enriched if v.get("verified"))
    flagged_count  = sum(1 for v in enriched if v.get("manual_lookup"))
    _log(f"\n  Enrichment complete: {verified_count} verified, {flagged_count} manual, "
          f"{len(vendors) - len(enriched)} dropped")

    return enriched


# ── Single vendor enrichment ──────────────────────────────────

def _crawl_contact_page(website: str) -> Dict:
    """
    Crawl the company's contact page. Returns emails, phone, AND page_text
    (so Groq can scan for obfuscated emails if regex finds nothing).
    5s timeout per request, max 2 page attempts.
    Returns {"found": bool, "emails": [], "phone": "", "page_text": ""}
    """
    domain = _extract_domain(website)
    if not domain:
        return {"found": False, "emails": [], "phone": "", "page_text": ""}

    # Expanded paths — covers most Gulf B2B site patterns
    contact_paths = ["/contact", "/contact-us", "/contactus", "/reach-us",
                     "/enquiry", "/get-in-touch", "/about-us", "/"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    best_text = ""
    # Try www. prefix too if not already present
    www_domain = domain if domain.startswith("www.") else "www." + domain

    for path in contact_paths[:8]:  # max 8 path attempts
        url = f"https://{domain}{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=CRAWL_TIMEOUT,
                                allow_redirects=True)
            if resp.status_code >= 400:
                continue
            soup   = BeautifulSoup(resp.text, "html.parser")
            text   = soup.get_text(separator=" ", strip=True)
            emails = [
                e for e in _extract_all_emails(text)
                if _email_matches_domain(e, domain) or
                   _email_matches_domain(e, _extract_domain(resp.url))
            ]
            phone  = _extract_phone(text)
            # 16KB — captures footer emails on long Gulf B2B pages
            text_trunc = text[:16000]
            if len(text_trunc) > len(best_text):
                best_text = text_trunc
            if emails or phone:
                print(f"      Crawl hit: {url} → {emails}")
                return {"found": True, "emails": emails, "phone": phone or "",
                        "page_text": text_trunc}
        except Exception:
            # Try http and www. fallbacks
            for fallback_url in [f"http://{domain}{path}", f"https://{www_domain}{path}", f"http://{www_domain}{path}"]:
                try:
                    resp = requests.get(fallback_url, headers=headers, timeout=CRAWL_TIMEOUT)
                    if resp.status_code == 200:
                        soup   = BeautifulSoup(resp.text, "html.parser")
                        text   = soup.get_text(separator=" ", strip=True)
                        emails = [e for e in _extract_all_emails(text)
                                  if _email_matches_domain(e, domain) or _email_matches_domain(e, www_domain)]
                        phone  = _extract_phone(text)
                        text_trunc = text[:8000]
                        if len(text_trunc) > len(best_text):
                            best_text = text_trunc
                        if emails or phone:
                            print(f"      Crawl hit ({fallback_url}): {emails}")
                            return {"found": True, "emails": emails, "phone": phone or "",
                                    "page_text": text_trunc}
                        break  # got a 200 response, no need to try more fallbacks for this path
                except Exception:
                    continue

    # Return page_text even if no emails found — Groq will scan it
    return {"found": bool(best_text), "emails": [], "phone": "", "page_text": best_text}


def _website_wrong_product(page_text: str, description: str, company_name: str) -> bool:
    """
    Keyword check: is the crawled page clearly from a DIFFERENT industry?
    Returns True (mismatch) ONLY when the page has zero product-relevant hits
    AND contains strong signals of a completely unrelated industry.
    Errs on the side of keeping suppliers — a trading company page may not list
    every product line explicitly.
    """
    if not page_text or len(page_text) < 150:
        return False  # Too little text to judge

    # Industries that are clearly unrelated to industrial B2B supply
    UNRELATED_MARKERS = [
        # Market research / reports
        "market research report", "market size", "market forecast", "cagr",
        "research report", "buy report", "purchase report",
        # Food / restaurant
        "menu", "restaurant", "cafe", "cuisine", "reservation", "dine",
        # Fashion / apparel
        "fashion", "clothing", "apparel", "footwear", "boutique",
        # Healthcare patient-facing
        "patient", "hospital", "clinic", "appointment", "diagnosis",
        # Real estate
        "property listing", "rent apartment", "buy apartment", "real estate agent",
        # Finance / banking
        "mutual fund", "stock market", "insurance policy", "credit card",
    ]

    page_lower = page_text[:6000].lower()

    # If page is clearly from an unrelated industry, it's a mismatch
    unrelated_hits = sum(1 for m in UNRELATED_MARKERS if m in page_lower)
    if unrelated_hits >= 2:
        return True

    stop = {
        "with", "from", "that", "this", "have", "will", "your", "more",
        "also", "been", "they", "were", "when", "what", "which", "their",
        "supplier", "company", "product", "service", "contact", "about",
        "industrial", "trading", "international", "group", "limited",
        "welcome", "home", "page", "click", "here", "privacy", "policy",
        "copyright", "reserved", "terms", "conditions", "email", "phone",
    }

    desc_words = list(dict.fromkeys(
        w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', description)
        if w.lower() not in stop
    ))
    keywords = desc_words[:20]

    if not keywords:
        return False

    hits = sum(1 for kw in keywords if kw in page_lower)

    # Only flag mismatch if ZERO relevant keywords found AND page has unrelated content
    if hits == 0 and unrelated_hits >= 1:
        return True

    return False


def _groq_extract_emails_from_text(page_text: str, domain: str) -> List[str]:
    """
    Ask Groq to extract emails from crawled page text, including obfuscated
    formats (e.g. "info [at] company [dot] com") that regex cannot match.
    Fast and free — Groq is ideal for this text-processing task.
    """
    if not page_text or len(page_text.strip()) < 40:
        return []

    prompt = f"""Extract email addresses from this text. Include obfuscated formats (e.g. "info [at] company.ae").
Prefer emails @{domain}

Text:
{page_text[:1500]}

Return JSON array only: ["info@company.com"] or []"""

    def _parse_emails(raw: str):
        clean  = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(clean)
        if isinstance(result, list):
            return [e.lower().strip() for e in result
                    if isinstance(e, str) and "@" in e and "." in e.split("@")[-1]]
        return []

    # Primary: Groq
    try:
        from services.groq_client import ask_groq
        return _parse_emails(ask_groq(prompt, json_mode=False, max_tokens=120))
    except Exception:
        pass

    # Fallback 1: OpenAI
    try:
        from services.openai_fallback import _call_openai
        return _parse_emails(_call_openai(prompt, model="gpt-4o-mini", max_tokens=200))
    except Exception:
        pass

    # Fallback 2: Claude
    try:
        from services.openai_fallback import _call_claude
        return _parse_emails(_call_claude(prompt, max_tokens=200))
    except Exception:
        return []


def _guess_email(domain: str) -> Optional[str]:
    """
    Return a best-guess email for the domain if it has a valid MX record.
    Prefers B2B-relevant prefixes in priority order.
    """
    if not domain:
        return None
    from services.email_verifier import _has_mx_record
    if not _has_mx_record(domain):
        return None
    # Return most likely B2B contact prefix
    return f"info@{domain}"


def _guess_emails_list(domain: str) -> List[str]:
    """
    Return guessed B2B email addresses for a domain.
    Does not require MX verification — guesses are shown as unverified in the UI.
    """
    if not domain:
        return []
    # Strip leading www. (string prefix, not character set)
    clean = domain[4:] if domain.startswith("www.") else domain
    if not clean:
        return []
    prefixes = ["info", "sales", "enquiries", "contact", "trade", "procurement"]
    return [f"{p}@{clean}" for p in prefixes]


def _enrich_single(
    vendor:            Dict,
    description:       str,
    country:           str,
    used_replacements: Set[str] = None,   # kept for API compatibility, unused
) -> Dict:
    """
    Contact enrichment pipeline. Azure B2 safe (~7s per vendor when website known).

    Pipeline:
      1. If website already known (from OpenAI/Claude discovery):
           → crawl directly — skip Sonar website-lookup entirely (~3s saved)
         If website NOT known:
           → Sonar live web search to find the official website
           → LLM fallback if Sonar is rate-limited
      2. BeautifulSoup crawl → scrape real email from the company's contact page
      3. Groq text parsing   → catches obfuscated emails that regex misses (FREE)
      4. Perplexity Sonar    → supplement if crawl + Groq both found nothing
      5. MX/DNS verify       → drop undeliverable addresses
    """
    name    = vendor.get("name", "")
    website = _clean_url(vendor.get("website", ""))

    # Strip junk directory URLs — they are not the company's own website
    if website:
        _wd = website.lower().replace("www.", "")
        for _jd in JUNK_DIRECTORY_DOMAINS:
            if _wd.startswith(_jd) or f"/{_jd}" in _wd or _wd == _jd:
                print(f"    ⚠️  Clearing junk directory URL for {name}: {website}")
                website = ""
                break
        # Also block if domain itself is in the junk set
        from urllib.parse import urlparse as _up
        try:
            _dom = _up(website).netloc.replace("www.", "").lower()
            if _dom in JUNK_DIRECTORY_DOMAINS:
                print(f"    ⚠️  Clearing junk directory URL for {name}: {website}")
                website = ""
        except Exception:
            pass

    # Manufacturer — flag for manual lookup, skip enrichment
    if vendor.get("source") == "manufacturer_direct":
        meta = _build_verification_metadata("manufacturer_direct", "", "",
                                            manual_lookup=True, phone_missing=True)
        return {**vendor, "verified": False, "manual_lookup": True,
                "verification_notes": "Manufacturer/brand — manual lookup required",
                **meta}

    sonar_emails  = []
    sonar_phone   = ""
    final_website = website

    # ── Step 1: Get official website ──────────────────────────
    if not final_website:
        # Website unknown — try Sonar (paid live web), then LLM fallback
        print(f"    No website — trying Sonar: {name}")
        sonar_result = _sonar_find_company(name, country, description)
        if not sonar_result:
            sonar_result = _llm_find_company_fallback(name, country, description)
        if not sonar_result:
            meta = _build_verification_metadata("manual_required", "", "",
                                                manual_lookup=True, phone_missing=True)
            return {
                **vendor,
                "email": "", "emails": [], "phone": "", "website": "",
                "verified": False, "manual_lookup": True,
                "verification_notes": "Website not found online — manual lookup required",
                **meta,
            }
        final_website = _root_url(_clean_url(sonar_result.get("website", "")))
        sonar_emails  = sonar_result.get("emails") or ([sonar_result["email"]] if sonar_result.get("email") else [])
        sonar_phone   = sonar_result.get("phone", "")
        print(f"    Sonar found website: {final_website}")
        # Validate Sonar-returned URL too — parked/dead domains still return 200
        if final_website and not _website_is_reachable(final_website):
            print(f"    ⚠️  Sonar website unreachable — asking LLM for correct URL")
            corrected = _claude_verify_website(name, country, description, final_website)
            final_website = corrected if corrected else ""
    else:
        # Normalize to root domain — strips deep paths that cause 404 on reachability check
        root = _root_url(final_website)
        if root != final_website:
            print(f"    Normalised website to root: {root}")
            final_website = root
        print(f"    Website from discovery: {final_website}")
        # Validate AI-suggested website before spending time crawling it
        if not _website_is_reachable(final_website):
            print(f"    ⚠️  Website unreachable — asking LLM for correct URL")
            corrected_url = _claude_verify_website(name, country, description, final_website)
            if corrected_url:
                final_website = corrected_url
            else:
                print(f"    ✖ All website fallbacks failed — clearing dead URL for {name}")
                final_website = ""

    # ── Step 2: Crawl contact page (FREE) ─────────────────────
    crawl_emails = []
    crawl_phone  = ""
    page_text    = ""
    product_mismatch = False
    if final_website:
        crawl = _crawl_contact_page(final_website)
        if crawl["found"]:
            crawl_emails = crawl["emails"]
            crawl_phone  = crawl["phone"]
        page_text = crawl.get("page_text", "")
        # Check website is actually about the right product (not a wrong company)
        if page_text and description:
            product_mismatch = _website_wrong_product(page_text, description, name)
            if product_mismatch:
                print(f"    ⚠️  Website content doesn't match product — flagging for review")

    # ── Step 3: Groq email extraction (FREE) ──────────────────
    # Finds obfuscated emails that BeautifulSoup regex cannot match.
    groq_emails: List[str] = []
    if not crawl_emails and page_text:
        domain = _extract_domain(final_website)
        groq_emails = _groq_extract_emails_from_text(page_text, domain)
        if groq_emails:
            print(f"    Groq extracted: {groq_emails}")

    # ── Step 4: Sonar supplement (PAID) ───────────────────────
    # Called when crawl+Groq found nothing — regardless of where website came from.
    if not crawl_emails and not groq_emails and not sonar_emails:
        print(f"    Sonar supplement (crawl+Groq failed): {name}")
        sonar_result = _sonar_find_company(name, country, description)
        if sonar_result:
            sonar_emails = sonar_result.get("emails") or ([sonar_result["email"]] if sonar_result.get("email") else [])
            sonar_phone  = sonar_result.get("phone", "") or sonar_phone
            # If Sonar found a different (better) website, update it
            sonar_site = _clean_url(sonar_result.get("website", ""))
            if sonar_site and sonar_site != final_website:
                print(f"    Sonar corrected website: {sonar_site}")
                final_website = sonar_site

    # ── Step 5: Merge + MX/DNS verify ─────────────────────────
    merged_emails = crawl_emails + groq_emails + [e for e in sonar_emails
                                                   if e not in crawl_emails + groq_emails]
    phone         = crawl_phone or sonar_phone

    # Filter out emails whose domain has zero overlap with company name or website domain
    # (catches emails accidentally scraped from a directory listing a different company)
    if final_website:
        site_domain = _extract_domain(final_website) or ""
        def _email_plausible(e: str) -> bool:
            if not e or "@" not in e:
                return False
            ed = e.split("@")[1].lower()
            if ed in LEGACY_EMAIL_DOMAINS:
                return True  # gmail/hotmail are always plausible personal contacts
            if site_domain and _email_matches_domain(e, site_domain):
                return True
            # Allow if email domain words overlap with company name
            co_words = set(re.findall(r'[a-z]{3,}', name.lower()))
            ed_words = set(re.findall(r'[a-z]{3,}', ed))
            return bool(co_words & ed_words)
        merged_emails = [e for e in merged_emails if _email_plausible(e)]

    all_emails    = filter_valid_emails(_rank_all_emails(merged_emails))
    email         = all_emails[0] if all_emails else ""
    legacy        = _is_legacy_domain(email)

    if all_emails or phone:
        if crawl_emails:
            method = "crawl"
        elif groq_emails:
            method = "groq_parse"
        else:
            method = "sonar_only"
        print(f"    [{method}] emails={all_emails or '—'} phone={phone or '—'}")
        meta = _build_verification_metadata(method, email, phone,
                                            legacy_domain=legacy, phone_missing=not phone)
        return {**vendor, "email": email, "emails": all_emails, "phone": phone,
                "website": final_website, "verified": True,
                "product_mismatch": product_mismatch, **meta}

    # Company confirmed to exist but no contact details found anywhere
    if final_website:
        # Last resort: generate pattern-based emails from the domain
        guess_domain = _extract_domain(final_website)
        guessed_emails = _guess_emails_list(guess_domain) if guess_domain else []
        print(f"    Guessed emails for {guess_domain}: {guessed_emails}")
        if guessed_emails:
            primary = guessed_emails[0]
            meta = _build_verification_metadata("sonar_only", primary, "",
                                                phone_missing=True)
            return {**vendor, "email": primary, "emails": guessed_emails, "phone": "",
                    "website": final_website, "verified": False, "manual_lookup": True,
                    "verification_notes": "Pattern-based emails generated — verify before sending",
                    **meta}
        meta = _build_verification_metadata("manual_required", "", "",
                                            manual_lookup=True, phone_missing=True)
        return {**vendor, "email": "", "emails": [], "phone": "",
                "website": final_website, "verified": False, "manual_lookup": True,
                "verification_notes": "Website found but no email detected — manual lookup required",
                **meta}

    # No website found — try guessing emails from the original vendor-provided website/domain
    original_url = _clean_url(vendor.get("website", ""))
    fallback_domain = _extract_domain(original_url) if original_url else ""
    guessed_emails = _guess_emails_list(fallback_domain) if fallback_domain else []
    if guessed_emails:
        print(f"    Fallback guessed emails from original URL ({fallback_domain}): {guessed_emails}")
        meta = _build_verification_metadata("manual_required", guessed_emails[0], "",
                                            manual_lookup=True, phone_missing=True)
        return {
            **vendor,
            "email": guessed_emails[0], "emails": guessed_emails, "phone": "",
            "website": original_url, "verified": False, "manual_lookup": True,
            "verification_notes": "Pattern-based emails — website not verified, manual lookup required",
            **meta,
        }

    meta = _build_verification_metadata("manual_required", "", "",
                                        manual_lookup=True, phone_missing=True)
    return {
        **vendor,
        "email": "", "emails": [], "phone": "", "website": original_url or "",
        "verified": False, "manual_lookup": True,
        "verification_notes": "No contact details found — manual lookup required",
        **meta,
    }


# ── Legacy (unused) ───────────────────────────────────────────

def _enrich_single_with_crawl(
    vendor:            Dict,
    description:       str,
    country:           str,
    used_replacements: Set[str] = None,
) -> Dict:
    """Legacy crawl-based enrichment — NOT used on Azure B2 (too slow/memory)."""
    if used_replacements is None:
        used_replacements = set()

    name    = vendor.get("name", "")
    website = _clean_url(vendor.get("website", ""))

    if vendor.get("source") == "manufacturer_direct":
        meta = _build_verification_metadata("manufacturer_direct", "", "",
                                            manual_lookup=True, phone_missing=True)
        return {**vendor, "verified": False, "manual_lookup": True,
                "verification_notes": "Manufacturer/brand — contact details require manual lookup",
                **meta}

    if website:
        print(f"    Step 1: Crawling known website: {website}")
        contacts = _crawl_for_contacts(website)
        if contacts.get("found"):
            emails_list = contacts.get("emails", [contacts.get("email", "")])
            email       = emails_list[0] if emails_list else ""
            phone       = contacts.get("phone", "")
            legacy      = _is_legacy_domain(email)
            if not phone:
                phone = _sonar_find_phone(name, website, country) or ""
            sonar_emails = _sonar_find_emails(name, website, country)
            all_emails   = _rank_all_emails(emails_list + sonar_emails)
            email        = all_emails[0] if all_emails else email
            meta = _build_verification_metadata("crawl_direct", email, phone,
                                                legacy_domain=legacy, phone_missing=not phone)
            return {**vendor, "email": email, "emails": all_emails, "phone": phone,
                    "website": website, "verified": True, **meta}

    print(f"    Step 2: Asking Sonar to find correct website for: {name}")
    sonar_result = _sonar_find_company(name, country, description)
    sonar_found  = sonar_result is not None

    if sonar_found:
        sonar_website = _clean_url(sonar_result.get("website", ""))
        sonar_emails  = sonar_result.get("emails") or ([sonar_result["email"]] if sonar_result.get("email") else [])
        sonar_email   = sonar_emails[0] if sonar_emails else ""
        sonar_phone   = sonar_result.get("phone", "")

        if sonar_website and sonar_website != website:
            print(f"    Step 2: Sonar found website: {sonar_website} — crawling to verify")
            contacts = _crawl_for_contacts(sonar_website)
            if contacts.get("found"):
                crawl_emails = contacts.get("emails", [contacts.get("email", "")])
                all_emails   = _rank_all_emails(crawl_emails + sonar_emails)
                email        = all_emails[0] if all_emails else ""
                phone        = contacts.get("phone", "")
                legacy       = _is_legacy_domain(email)
                if not phone:
                    print(f"    Step 2: Phone missing — secondary phone search")
                    phone = _sonar_find_phone(name, sonar_website, country) or ""
                print(f"    Step 2: Found {len(all_emails)} email(s): {all_emails}")
                meta = _build_verification_metadata("crawl_sonar", email, phone,
                                                    legacy_domain=legacy, phone_missing=not phone)
                return {**vendor, "email": email, "emails": all_emails, "phone": phone,
                        "website": sonar_website, "verified": True, **meta}

        if sonar_emails or sonar_phone:
            print(f"    Step 2: Sonar found company — using Sonar contacts (crawl failed)")
            all_emails = _rank_all_emails(sonar_emails)
            email      = all_emails[0] if all_emails else ""
            phone      = sonar_phone
            legacy     = _is_legacy_domain(email)
            if not phone:
                phone = _sonar_find_phone(name, sonar_website or website, country) or ""
            print(f"    Step 2: Found {len(all_emails)} email(s): {all_emails}")
            meta = _build_verification_metadata("sonar_only", email, phone,
                                                legacy_domain=legacy, phone_missing=not phone)
            return {**vendor, "email": email, "emails": all_emails, "phone": phone,
                    "website": sonar_website or website, "verified": True, **meta}

        print(f"    Step 2: Sonar confirmed company — flagging for manual lookup")
        meta = _build_verification_metadata("manual_required", "", "",
                                            manual_lookup=True, phone_missing=True)
        return {**vendor, "email": "", "emails": [], "phone": "",
                "website": sonar_result.get("website","") or website,
                "verified": False, "manual_lookup": True, **meta}

    # ── Step 3: Find alternative ─────────────────────────────
    print(f"    Step 2 failed: Sonar couldn't find '{name}' — suspected hallucination")
    print(f"    Step 3: Searching for verified real alternative")

    alternative = _sonar_find_alternative(
        name, description, country,
        exclude_names=used_replacements,
    )

    if alternative:
        # Fix 5: Reject non-Gulf alternatives when delivery is UAE/Gulf
        alt_country = (alternative.get("country") or "").lower()
        if country.lower() in {"uae", "qatar", "saudi arabia", "kuwait", "oman", "bahrain"}:
            if alt_country and not any(g in alt_country for g in GULF_COUNTRIES):
                print(f"    Step 3: Skipping non-Gulf alternative: {alternative.get('name')} ({alternative.get('country')})")
                alternative = None

    if alternative:
        alt_name    = alternative.get("name", "")
        alt_norm    = _normalize_company_name(alt_name)
        alt_website = _clean_url(alternative.get("website", ""))
        alt_emails  = alternative.get("emails") or ([alternative["email"]] if alternative.get("email") else [])
        alt_email   = alt_emails[0] if alt_emails else ""
        alt_phone   = alternative.get("phone", "")

        if alt_website:
            print(f"    Step 3: Crawling alternative: {alt_website}")
            contacts = _crawl_for_contacts(alt_website)
            if contacts.get("found"):
                crawl_emails = contacts.get("emails", [contacts.get("email", "")])
                all_emails   = _rank_all_emails(crawl_emails + alt_emails)
                email        = all_emails[0] if all_emails else ""
                phone        = contacts.get("phone", "") or alt_phone
                legacy       = _is_legacy_domain(email)
                if not phone:
                    phone = _sonar_find_phone(alt_name, alt_website, country) or ""
                print(f"    Step 3: ✅ Alternative verified: {alt_name} | {len(all_emails)} email(s)")
                used_replacements.add(alt_norm)
                meta = _build_verification_metadata("replaced", email, phone,
                                                    legacy_domain=legacy, phone_missing=not phone)
                return {
                    **vendor, "email": email, "emails": all_emails, "phone": phone,
                    "name":               alt_name,
                    "website":            alt_website,
                    "country":            alternative.get("country", vendor.get("country")),
                    "city":               alternative.get("city",    vendor.get("city")),
                    "description":        alternative.get("description", vendor.get("description")),
                    "sourcing_rationale": alternative.get("sourcing_rationale", vendor.get("sourcing_rationale")),
                    "verified":           True,
                    "replaced_from":      name,
                    **meta,
                }

        if alt_email or alt_phone:
            all_emails = _rank_all_emails(alt_emails)
            email      = all_emails[0] if all_emails else ""
            legacy     = _is_legacy_domain(email)
            used_replacements.add(alt_norm)
            meta = _build_verification_metadata("replaced_sonar_only", email, alt_phone,
                                                legacy_domain=legacy, phone_missing=not alt_phone)
            return {
                **vendor,
                "name": alt_name, "email": email, "emails": all_emails, "phone": alt_phone,
                "website": alt_website or "", "verified": True,
                "replaced_from": name, **meta,
            }

    return {
        **vendor,
        "email": "", "emails": [], "phone": "", "website": website,
        "verified": False, "manual_lookup": False,
        "drop_reason": f"Sonar couldn't find '{name}' and no verified Gulf alternative found",
        **_build_verification_metadata("manual_required", "", "", phone_missing=True),
    }


# ── Web crawling ──────────────────────────────────────────────

def _crawl_for_contacts(base_url: str) -> Dict:
    """Fix 4: uses relaxed domain matching for email validation."""
    domain = _extract_domain(base_url)
    if not domain:
        return {"found": False}

    all_emails  = []
    all_phones  = []
    crawled_url = ""

    for path in CONTACT_PAGE_PATHS[:MAX_CRAWL_PAGES]:
        url = f"https://{domain}{path}"
        try:
            resp = requests.get(url, headers=HEADERS,
                                timeout=CRAWL_TIMEOUT, allow_redirects=True)
            if resp.status_code != 200:
                continue

            final_domain = _extract_domain(resp.url)
            soup         = BeautifulSoup(resp.text, "html.parser")
            text         = soup.get_text(separator=" ", strip=True)
            page_emails  = _extract_all_emails(text)
            page_phone   = _extract_phone(text)

            # Fix 4: relaxed domain matching
            matched_emails = [
                e for e in page_emails
                if _email_matches_domain(e, domain) or
                   _email_matches_domain(e, final_domain)
            ]
            dropped_emails = [e for e in page_emails if e not in matched_emails]
            if dropped_emails:
                print(f"      ⚠️  Email domain mismatch — dropped: {dropped_emails}")

            if matched_emails or page_phone:
                all_emails.extend(matched_emails)
                if page_phone:
                    all_phones.append(page_phone)
                if not crawled_url:
                    crawled_url = url

            time.sleep(CRAWL_DELAY)

        except requests.exceptions.SSLError:
            try:
                url_http = f"http://{domain}{path}"
                resp     = requests.get(url_http, headers=HEADERS, timeout=CRAWL_TIMEOUT)
                if resp.status_code == 200:
                    soup           = BeautifulSoup(resp.text, "html.parser")
                    text           = soup.get_text(separator=" ", strip=True)
                    page_emails    = _extract_all_emails(text)
                    matched_emails = [e for e in page_emails if _email_matches_domain(e, domain)]
                    page_phone     = _extract_phone(text)
                    if matched_emails or page_phone:
                        all_emails.extend(matched_emails)
                        if page_phone:
                            all_phones.append(page_phone)
                        if not crawled_url:
                            crawled_url = url_http
            except Exception:
                pass

        except requests.exceptions.ConnectionError:
            print(f"      ⚠️  Could not connect to {url}")
            break
        except Exception as e:
            print(f"      ⚠️  Crawl error on {url}: {e}")
            continue

    if not all_emails and not all_phones:
        return {"found": False}

    ranked = _rank_all_emails(all_emails)
    return {
        "found":       True,
        "email":       ranked[0] if ranked else "",
        "emails":      ranked,          # all unique verified emails, ranked
        "phone":       all_phones[0] if all_phones else "",
        "crawled_url": crawled_url,
    }


# ── Sonar API calls ───────────────────────────────────────────

def _llm_find_company_fallback(
    company_name: str,
    country:      str,
    description:  str,
) -> Optional[Dict]:
    """
    LLM-based fallback when Sonar is exhausted.
    Uses the ask_llm router (Groq → OpenAI → Anthropic) to guess
    the website and contact email for a known company.
    Lower confidence than Sonar — used only when Sonar is unavailable.
    """
    try:
        from services.llm_router import ask_llm_json
        result = ask_llm_json(f"""Official website and contact email for:
Company: {company_name} | Country: {country} | Industry: {description[:60]}
JSON: {{"company_found":true,"website":"https://...","email":"info@...","phone":"+971..."}}
If unknown: {{"company_found":false}}""",
            max_tokens=120,
        )
        if not result.get("company_found"):
            return None
        print(f"      🤖 LLM fallback found: {result.get('website','?')}")
        return result
    except Exception as e:
        print(f"      ⚠️  LLM company fallback error: {e}")
        return None


def _sonar_find_company(
    company_name: str,
    country:      str,
    description:  str,
) -> Optional[Dict]:
    if not SONAR_API_KEY:
        return None

    prompt = f"""Find the official website and contact details for this company:

Company: {company_name}
Country: {country}
They are expected to be a supplier of: {description}

I need:
1. Their official company website (NOT a product page on Amazon/Noon/marketplace)
2. ALL contact emails visible on their website — include info@, sales@, enquiries@, and any department-specific emails (up to 4 emails)
3. A phone number with country code

If you cannot find this exact company with confidence, say so clearly.
Do not provide details for a different company.

Return ONLY a JSON object:
{{
  "company_found": true,
  "name": "exact company name",
  "website": "https://example.com",
  "emails": ["info@example.com", "sales@example.com"],
  "email": "info@example.com",
  "phone": "+971 4 123 4567",
  "confidence": "high"
}}"""

    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {SONAR_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "sonar",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 500},
            timeout=20,
        )
        if resp.status_code != 200:
            return None

        content = resp.json()["choices"][0]["message"]["content"].strip()
        clean   = re.sub(r"```json|```", "", content).strip()
        result  = json.loads(clean)

        if not result.get("company_found"):
            print(f"      Sonar: company not found or low confidence")
            return None
        if result.get("confidence") == "low":
            print(f"      Sonar: low confidence — skipping")
            return None

        # Fix 2/4: Reject if website is a B2C marketplace
        website = result.get("website", "")
        from services.sonar_discovery import is_b2c_vendor
        if is_b2c_vendor({"website": website, "name": ""}):
            print(f"      Sonar: returned B2C website {website} — skipping")
            return None

        return result

    except json.JSONDecodeError:
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            email   = _pick_best_email(_extract_all_emails(content))
            url     = _extract_url(content)
            phone   = _extract_phone(content)
            if url or email:
                return {"company_found": True, "name": company_name,
                        "website": url, "email": email, "phone": phone}
        except Exception:
            pass
        return None
    except Exception as e:
        msg = str(e).lower()
        is_exhausted = any(p in msg for p in (
            "rate limit", "429", "quota", "exceeded", "too many requests"
        ))
        if is_exhausted:
            print(f"      ⚠️  Sonar exhausted — falling back to LLM for company lookup")
            return _llm_find_company_fallback(company_name, country, description)
        print(f"      ⚠️  Sonar find_company error: {e}")
        return None




# ── Email and phone helpers ───────────────────────────────────

def _extract_all_emails(text: str) -> List[str]:
    skip = ["noreply","no-reply","donotreply","example.com","yourname","domain.com"]
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    seen, result = set(), []
    for match in re.findall(pattern, text):
        m = match.lower()
        if m not in seen and not any(s in m for s in skip):
            seen.add(m); result.append(m)
    return result


def _is_preferred_email(email: str) -> bool:
    local = email.split("@")[0].lower() if "@" in email else email.lower()
    return any(local.startswith(p) for p in PREFERRED_EMAIL_PREFIXES)


def _is_deprioritized_email(email: str) -> bool:
    local = email.split("@")[0].lower() if "@" in email else email.lower()
    return any(local.startswith(p) for p in DEPRIORITIZED_EMAIL_PREFIXES)


def _pick_best_email(emails: List[str]) -> str:
    ranked = _rank_all_emails(emails)
    return ranked[0] if ranked else ""


def _rank_all_emails(emails: List[str]) -> List[str]:
    """
    Dedup, remove noise, then sort: preferred prefixes first,
    deprioritized last. Returns up to 5 unique emails.
    """
    if not emails:
        return []
    seen, unique = set(), []
    for e in emails:
        e = e.lower().strip()
        if e and e not in seen:
            seen.add(e)
            unique.append(e)

    def _score(e):
        local = e.split("@")[0]
        if _is_preferred_email(e):
            return 0
        if _is_deprioritized_email(e):
            return 2
        return 1

    unique.sort(key=_score)
    return unique[:5]


def _extract_phone(text: str) -> str:
    uae_patterns = [
        r"\+971[\s\.\-]?(?:0[\s\.\-]?)?[2-9]\d[\s\.\-]?\d{3}[\s\.\-]?\d{4}",
        r"\+971[\s\.\-]?\d{8,10}",
        r"00971[\s\.\-]?\d{8,10}",
        r"(?<!\d)0[2-9]\d[\s\.\-]?\d{3}[\s\.\-]?\d{4}(?!\d)",
        r"\(\+971\)[\s\.\-]?\d[\d\s\.\-]{7,12}",
    ]
    for pat in uae_patterns:
        match = re.search(pat, text)
        if match: return re.sub(r"[\s]", "", match.group()).strip()
    match = re.search(r"\+(?:974|966|965|968|973|967)[\s\.\-]?\d[\d\s\.\-]{7,12}\d", text)
    if match: return match.group().strip()
    match = re.search(r"\+\d{1,3}[\s\.\-]?\(?\d{1,4}\)?[\s\.\-]?\d[\d\s\.\-]{5,12}\d", text)
    if match: return match.group().strip()
    return ""


def _extract_url(text: str) -> str:
    match = re.search(r"https?://[^\s\"'<>]+", text)
    return match.group().rstrip(".,;)") if match else ""


def _clean_url(url: str) -> str:
    if not url: return ""
    url = url.strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def _root_url(url: str) -> str:
    """Strip path from URL — keeps only scheme + domain. www.bp.com/en_ae/uae.html → https://www.bp.com"""
    if not url: return ""
    url = _clean_url(url)
    from urllib.parse import urlparse as _up
    try:
        p = _up(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return url


def _extract_domain(url: str) -> str:
    if not url: return ""
    url   = _clean_url(url)
    match = re.search(r"https?://([^/]+)", url)
    return match.group(1) if match else ""