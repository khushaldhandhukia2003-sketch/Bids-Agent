"""
services/email_verifier.py

Lightweight email verification — no external API, no cost, B2-safe.

What it checks:
  1. Format validity (regex)
  2. MX record exists for the domain (DNS — proves the domain CAN receive email)
  3. Not a disposable/free domain (gmail, hotmail, yahoo etc — B2C flag)
  4. Not a known catch-all pattern (info@, sales@ are fine; test@, noreply@ are not)

What it does NOT do:
  - SMTP ping (blocked by 90% of mail servers, unreliable)
  - Paid verification APIs (ZeroBounce etc — overkill for B2B industrial contacts)

Result: "valid" | "invalid" | "unverifiable"
"""

import re
import socket
from typing import Dict, List

# Free/personal email domains — flag as B2C, not B2B contacts
_FREE_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "icloud.com", "me.com", "aol.com", "protonmail.com", "mail.com",
    "yandex.com", "zoho.com", "rediffmail.com",
}

# These local parts are almost certainly dead/wrong
_DEAD_LOCAL_PARTS = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "test", "admin123", "user", "webmaster123",
    "bounce", "mailer-daemon",
}

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _has_mx_record(domain: str) -> bool:
    """DNS MX lookup — proves the domain is set up to receive email."""
    try:
        # getaddrinfo with mx type isn't available without dnspython,
        # but socket can resolve the domain. Full MX needs dnspython.
        # Fallback: just verify domain resolves (A record).
        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "MX", lifetime=3)
            return bool(answers)
        except ImportError:
            # dnspython not installed — fall back to A record check
            socket.setdefaulttimeout(3)
            socket.getaddrinfo(domain, None)
            return True
    except Exception:
        return False


def verify_email(email: str) -> Dict:
    """
    Returns:
      { "email": str, "status": "valid"|"invalid"|"unverifiable",
        "reason": str, "is_free_domain": bool }
    """
    email = (email or "").strip().lower()

    if not email:
        return {"email": email, "status": "invalid", "reason": "empty", "is_free_domain": False}

    if not _EMAIL_RE.match(email):
        return {"email": email, "status": "invalid", "reason": "bad_format", "is_free_domain": False}

    local, domain = email.split("@", 1)

    if local in _DEAD_LOCAL_PARTS:
        return {"email": email, "status": "invalid", "reason": "dead_local_part", "is_free_domain": False}

    is_free = domain in _FREE_DOMAINS
    if is_free:
        # Free domains are real emails but not B2B company contacts
        return {"email": email, "status": "valid", "reason": "free_domain", "is_free_domain": True}

    # MX / domain resolution check — treat DNS failure as "unverifiable", not "invalid"
    if not _has_mx_record(domain):
        return {"email": email, "status": "unverifiable", "reason": "domain_no_mx", "is_free_domain": False}

    return {"email": email, "status": "valid", "reason": "mx_verified", "is_free_domain": False}


def verify_emails_list(emails: List[str]) -> List[Dict]:
    """Verify a list of emails, return only valid/unverifiable ones sorted best-first."""
    results = [verify_email(e) for e in emails if e]
    # Keep valid AND unverifiable (MX timeout) — drop only definitively invalid
    kept = [r for r in results if r["status"] in ("valid", "unverifiable")]
    kept.sort(key=lambda r: (0 if r["reason"] == "mx_verified" else 1))
    return kept


def filter_valid_emails(emails: List[str]) -> List[str]:
    """Return email strings that are valid or unverifiable (not definitively invalid), best first."""
    return [r["email"] for r in verify_emails_list(emails)]
