"""
services/vendor_storage.py

Saves newly discovered and contact-enriched vendors to vendors_master table.
Skips vendors that already exist (matched by normalized vendor_name).
Returns count of rows actually inserted.
"""

import re
from typing import List, Dict
from datetime import datetime


def _normalize_name(name: str) -> str:
    n = name.lower().strip()
    for suffix in [r"\bllc\b", r"\bltd\b", r"\binc\b", r"\bco\b",
                   r"\bfze\b", r"\bfzc\b", r"\bsaog\b", r"\bwll\b"]:
        n = re.sub(suffix, "", n)
    return re.sub(r"[^\w\s]", "", n).strip()


def save_new_vendors(
    vendors: List[Dict],
    inquiry_context: str,
    db_conn,
) -> Dict:
    """
    Insert new vendors into vendors_master.
    Skips rows where vendor_name already exists (case-insensitive, normalized).

    Args:
        vendors:         List of enriched vendor dicts from contact_enrichment
        inquiry_context: Short string describing the inquiry (used as sourcing_rationale)
        db_conn:         Active psycopg2 connection

    Returns:
        {"saved": int, "skipped": int, "errors": int}
    """
    if not vendors:
        return {"saved": 0, "skipped": 0, "errors": 0}

    cursor = db_conn.cursor()
    saved = skipped = errors = 0

    try:
        # Fetch existing names once for dedup check
        cursor.execute("SELECT LOWER(vendor_name) FROM vendors_master")
        existing_names = {row[0].strip() for row in cursor.fetchall()}

        for v in vendors:
            name = (v.get("name") or "").strip()
            if not name:
                skipped += 1
                continue

            # Collect all emails — prefer `emails` list, fall back to `email` field
            raw_emails  = v.get("emails") or []
            single_email = (v.get("email") or "").strip()
            if not raw_emails and single_email:
                raw_emails = [e.strip() for e in single_email.split(",") if e.strip()]
            # Only save vendors with at least one genuine email
            valid_emails = [e for e in raw_emails if "@" in e and "." in e.split("@")[-1]]
            if not valid_emails:
                print(f"  [storage] Skip (no email): {name}")
                skipped += 1
                continue
            email = ", ".join(valid_emails)  # store all emails comma-separated

            norm = _normalize_name(name)
            if not norm:
                skipped += 1
                continue

            # Skip if already in DB
            if name.lower() in existing_names or norm in {_normalize_name(e) for e in existing_names}:
                print(f"  [storage] Skip (exists): {name}")
                skipped += 1
                continue

            # Map vendor dict fields to vendors_master columns
            conf_raw = v.get("verification_confidence") or v.get("confidence_score") or 0.5
            # Normalize to 0-1 range (some scores come in as 0-10)
            conf = float(conf_raw) / 10.0 if float(conf_raw) > 1.0 else float(conf_raw)
            conf = min(max(conf, 0.0), 1.0)

            try:
                cursor.execute("""
                    INSERT INTO vendors_master (
                        vendor_name,
                        country,
                        city,
                        email,
                        phone,
                        website,
                        brands,
                        sourcing_rationale,
                        description,
                        channel_codes,
                        verification_confidence,
                        source,
                        updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    name,
                    v.get("country") or "",
                    v.get("city")    or "",
                    v.get("email")   or "",
                    v.get("phone")   or "",
                    v.get("website") or "",
                    v.get("brands")  or "",
                    inquiry_context[:500],
                    v.get("description") or v.get("sourcing_rationale") or "",
                    v.get("channel_code") or "",
                    conf,
                    v.get("source") or "ai_discovered",
                    datetime.utcnow(),
                ))
                existing_names.add(name.lower())
                saved += 1
                print(f"  [storage] Saved: {name}")
            except Exception as row_err:
                print(f"  [storage] Error saving {name}: {row_err}")
                errors += 1

        db_conn.commit()

    except Exception as e:
        db_conn.rollback()
        print(f"  [storage] Fatal error: {e}")
        raise
    finally:
        cursor.close()

    print(f"  [storage] Done — saved:{saved} skipped:{skipped} errors:{errors}")
    return {"saved": saved, "skipped": skipped, "errors": errors}
