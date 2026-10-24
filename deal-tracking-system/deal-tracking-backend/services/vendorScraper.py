"""
services/vendorScraper.py
UAE-specific vendor scraping across 5 sources.

Changed: extract_product_with_claude() and verify_vendors_with_claude()
now use ask_groq() instead of the Anthropic client.
Everything else (scrapers, dedup, main entry point) is untouched.
"""
import requests
import time
import re
import json
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from services.groq_client import ask_groq
import os

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ── Utility ───────────────────────────────────────────────────
def clean(val) -> Optional[str]:
    if not val: return None
    return " ".join(str(val).split()).strip() or None

def get_soup(url: str, timeout=12) -> Optional[BeautifulSoup]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [SCRAPE ERROR] {url} → {e}")
        return None


# ── Source 1: yellowpages.ae ──────────────────────────────────
def scrape_yellowpages(product: str) -> List[Dict]:
    print(f"  Scraping yellowpages.ae for: {product}")
    vendors = []
    query   = product.replace(" ", "+")
    url     = f"https://www.yellowpages.ae/search?q={query}&l=UAE"
    soup    = get_soup(url)
    if not soup: return vendors

    for item in soup.select(".listing, .business-listing, .yp-listing")[:8]:
        name    = item.select_one(".business-name, .name, h2, h3")
        phone   = item.select_one(".phone, .tel, [class*='phone']")
        email   = item.select_one("[href^='mailto:']")
        address = item.select_one(".address, .location, [class*='address']")
        website = item.select_one("a[href^='http']:not([href*='yellowpages'])")
        vendor  = {
            "source":     "yellowpages.ae",
            "name":       clean(name.text)    if name    else None,
            "phone":      clean(phone.text)   if phone   else None,
            "email":      email["href"].replace("mailto:", "") if email else None,
            "address":    clean(address.text) if address else None,
            "website":    website["href"]     if website else None,
            "categories": None,
        }
        if vendor["name"]:
            vendors.append(vendor)

    print(f"    → Found {len(vendors)} vendors")
    return vendors


# ── Source 2: dubizzle.com/business ──────────────────────────
def scrape_dubizzle(product: str) -> List[Dict]:
    print(f"  Scraping dubizzle.com for: {product}")
    vendors = []
    query   = product.replace(" ", "-").lower()
    url     = f"https://business.dubizzle.com/en/search/?q={query}"
    soup    = get_soup(url)
    if not soup: return vendors

    for item in soup.select(".listing-card, .business-card, [class*='listing']")[:8]:
        name    = item.select_one("h2, h3, .title, .name")
        phone   = item.select_one("[class*='phone'], [href^='tel:']")
        address = item.select_one("[class*='location'], [class*='address']")
        cats    = item.select_one("[class*='category'], [class*='tag']")
        vendor  = {
            "source":     "dubizzle.com",
            "name":       clean(name.text)    if name    else None,
            "phone":      clean(phone.text)   if phone   else None,
            "email":      None,
            "address":    clean(address.text) if address else None,
            "website":    None,
            "categories": clean(cats.text)    if cats    else None,
        }
        if vendor["name"]:
            vendors.append(vendor)

    print(f"    → Found {len(vendors)} vendors")
    return vendors


# ── Source 3: tradearabia.com ─────────────────────────────────
def scrape_tradearabia(product: str) -> List[Dict]:
    print(f"  Scraping tradearabia.com for: {product}")
    vendors = []
    query   = product.replace(" ", "+")
    url     = f"https://www.tradearabia.com/search/?q={query}&type=company"
    soup    = get_soup(url)
    if not soup: return vendors

    for item in soup.select(".company-result, .search-result, article")[:8]:
        name    = item.select_one("h2, h3, .company-name, .title")
        address = item.select_one(".location, .country, [class*='location']")
        website = item.select_one("a[href^='http']")
        cats    = item.select_one(".sector, .industry, [class*='category']")
        vendor  = {
            "source":     "tradearabia.com",
            "name":       clean(name.text)    if name    else None,
            "phone":      None,
            "email":      None,
            "address":    clean(address.text) if address else None,
            "website":    website["href"]     if website else None,
            "categories": clean(cats.text)    if cats    else None,
        }
        if vendor["name"]:
            vendors.append(vendor)

    print(f"    → Found {len(vendors)} vendors")
    return vendors


# ── Source 4: gulf-directory.com ─────────────────────────────
def scrape_gulf_directory(product: str) -> List[Dict]:
    print(f"  Scraping gulf-directory.com for: {product}")
    vendors = []
    query   = product.replace(" ", "+")
    url     = f"https://www.gulf-directory.com/search.html?q={query}&country=UAE"
    soup    = get_soup(url)
    if not soup: return vendors

    for item in soup.select(".company, .listing, .result-item")[:8]:
        name    = item.select_one("h2, h3, .company-name")
        phone   = item.select_one(".phone, [class*='phone']")
        email   = item.select_one("[href^='mailto:']")
        address = item.select_one(".address, .location")
        website = item.select_one("a[href^='http']:not([href*='gulf-directory'])")
        vendor  = {
            "source":     "gulf-directory.com",
            "name":       clean(name.text)    if name    else None,
            "phone":      clean(phone.text)   if phone   else None,
            "email":      email["href"].replace("mailto:", "") if email else None,
            "address":    clean(address.text) if address else None,
            "website":    website["href"]     if website else None,
            "categories": None,
        }
        if vendor["name"]:
            vendors.append(vendor)

    print(f"    → Found {len(vendors)} vendors")
    return vendors


# ── Source 5: Google Search (UAE) ─────────────────────────────
def scrape_google_uae(product: str) -> List[Dict]:
    print(f"  Scraping Google UAE for: {product}")
    vendors = []
    query   = f"{product} supplier UAE site:ae OR UAE vendor"
    url     = f"https://www.google.com/search?q={query.replace(' ', '+')}&gl=ae&hl=en&num=10"
    soup    = get_soup(url)
    if not soup: return vendors

    for item in soup.select(".g, .tF2Cxc")[:8]:
        title   = item.select_one("h3")
        link    = item.select_one("a")
        snippet = item.select_one(".VwiC3b, .s3v9rd, .st")
        if not title: continue
        vendor  = {
            "source":     "google.ae",
            "name":       clean(title.text),
            "phone":      None,
            "email":      None,
            "address":    None,
            "website":    link["href"] if link else None,
            "categories": clean(snippet.text)[:100] if snippet else None,
        }
        vendors.append(vendor)

    print(f"    → Found {len(vendors)} vendors")
    return vendors


# ── Groq: Extract product from RFQ text ───────────────────────
def extract_product_with_claude(rfq_text: str) -> Dict:
    """Kept original function name so nothing else needs to change."""
    print("  Asking Groq to extract product details...")
    try:
        prompt = f"""Extract product details from this RFQ text.
Return ONLY valid JSON with these exact keys:
{{
  "product_name": "main product name (short, 3-5 words)",
  "brand": "brand/manufacturer if mentioned, else null",
  "quantity": "quantity if mentioned, else null",
  "specs": "key specifications, else null",
  "search_query": "best 3-word search query to find UAE suppliers"
}}

RFQ Text:
{rfq_text[:2000]}"""

        text   = ask_groq(prompt, max_tokens=500)
        text   = re.sub(r"```json|```", "", text).strip()
        return json.loads(text)

    except Exception as e:
        print(f"  Groq extraction error: {e}")
        return {"product_name": rfq_text[:50], "search_query": rfq_text[:30]}


# ── Groq: Verify & rank vendors ───────────────────────────────
def verify_vendors_with_claude(vendors: List[Dict], product: str) -> List[Dict]:
    """Kept original function name so nothing else needs to change."""
    if not vendors:
        return vendors
    print(f"  Groq verifying {len(vendors)} vendors...")
    try:
        vendor_list = json.dumps([
            {"name": v.get("name"), "address": v.get("address"), "website": v.get("website")}
            for v in vendors
        ], indent=2)

        prompt = f"""For the product "{product}", review these UAE vendors.
Return a JSON array — same vendors with 3 new fields added to each:
- "relevance_score": 1-10 (how likely they supply this product)
- "verified": true or false (looks like a real UAE business)
- "notes": one line about why they are relevant

Vendors:
{vendor_list}

Return ONLY the JSON array, no explanation."""

        text     = ask_groq(prompt, max_tokens=800)
        text     = re.sub(r"```json|```", "", text).strip()

        # Extract array safely
        start    = text.find("[")
        end      = text.rfind("]") + 1
        verified = json.loads(text[start:end]) if start != -1 else []

        for i, v in enumerate(vendors):
            if i < len(verified):
                v["relevance_score"] = verified[i].get("relevance_score", 5)
                v["verified"]        = verified[i].get("verified", False)
                v["notes"]           = verified[i].get("notes", "")

        vendors.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    except Exception as e:
        print(f"  Groq verification error: {e}")
        for v in vendors:
            v.setdefault("relevance_score", 5)
            v.setdefault("verified", False)
            v.setdefault("notes", "")

    return vendors


# ── Main entry point (unchanged) ─────────────────────────────
def scrape_uae_vendors(product_query: str, rfq_text: str = None) -> Dict:
    print(f"\n{'='*50}")
    print(f"UAE Vendor Search: {product_query}")
    print(f"{'='*50}")

    product_info = {}
    if rfq_text:
        product_info = extract_product_with_claude(rfq_text)
        search_query = product_info.get("search_query", product_query)
        print(f"  Groq extracted: {product_info.get('product_name')} → search: {search_query}")
    else:
        search_query = product_query

    all_vendors = []
    for scraper in [scrape_yellowpages, scrape_dubizzle, scrape_tradearabia,
                    scrape_gulf_directory, scrape_google_uae]:
        try:
            all_vendors.extend(scraper(search_query))
            time.sleep(1)
        except Exception as e:
            print(f"  Scraper {scraper.__name__} failed: {e}")

    seen, unique = set(), []
    for v in all_vendors:
        name = (v.get("name") or "").lower()
        if name and name not in seen:
            seen.add(name)
            unique.append(v)

    print(f"\n  Total unique vendors found: {len(unique)}")
    verified = verify_vendors_with_claude(unique, search_query)

    return {
        "product_info": product_info,
        "search_query": search_query,
        "total_found":  len(verified),
        "vendors":      verified,
        "sources_used": ["yellowpages.ae", "dubizzle.com", "tradearabia.com",
                         "gulf-directory.com", "google.ae"],
    }