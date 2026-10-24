"""
routes/zoho_sync.py
Zoho CRM ↔ bids_tracking sync — Phase 3

Credentials are stored server-side ONLY via environment variables.
They are never sent to or shown in the frontend.

Required env vars (set in your shell, .env, or Azure App Settings):
  ZOHO_CLIENT_ID
  ZOHO_CLIENT_SECRET
  ZOHO_REFRESH_TOKEN
  ZOHO_DC      (optional, default "com") — com / in / eu / au / jp
  ZOHO_MODULE  (optional, default "Deals")

Endpoints:
  POST /zoho/sync           — pull Deals from Zoho, upsert bids_tracking
  GET  /zoho/sync/log       — last N sync runs
  POST /zoho/push/{bid_id}  — push a bid status change back to Zoho
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
import urllib.request
import urllib.parse

from database import get_db, get_connection
from zoho_config import (
    ZOHO_CLIENT_ID,
    ZOHO_CLIENT_SECRET,
    ZOHO_REFRESH_TOKEN,
    ZOHO_DC,
    ZOHO_MODULE,
)

router = APIRouter(prefix="/zoho", tags=["Zoho Sync"])

# In-memory sync state (reset on restart)
_sync_state: dict = {"running": False, "started_at": None, "result": None, "error": None}


def _check_configured():
    if not ZOHO_CLIENT_ID or not ZOHO_CLIENT_SECRET or not ZOHO_REFRESH_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Zoho credentials not set. Configure ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN as server environment variables."
        )


def _refresh_access_token() -> str:
    """Exchange stored refresh token for a short-lived access token."""
    url = f"https://accounts.zoho.{ZOHO_DC}/oauth/v2/token"
    params = urllib.parse.urlencode({
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id":     ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type":    "refresh_token",
    })
    req = urllib.request.Request(f"{url}?{params}", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Zoho token refresh failed: {e}")
    if "access_token" not in d:
        raise HTTPException(status_code=401, detail=f"Zoho token error: {d}")
    return d["access_token"]


def _zoho_request(url: str, token: str, method="GET", data: dict = None) -> dict:
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Zoho-oauthtoken {token}")
    req.add_header("Content-Type", "application/json")
    if data:
        req.data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=e.code, detail=f"Zoho API error: {body[:400]}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Zoho unreachable: {e}")


# Maps actual Zoho field values → internal status
STAGE_MAP = {
    "bid won":       "won",
    "bid lost":      "lost",
    "closed won":    "won",
    "closed lost":   "lost",
    "won":           "won",
    "lost":          "lost",
    "bid pending":   "bid_sent",
    "bid submitted": "bid_sent",
    "quoted":        "quoted",
    "proposal":      "quoted",
}

ENQUIRY_STATUS_MAP = {
    "quoted":    "quoted",
    "pending":   "bid_sent",
    "regretted": "lost",
    "won":       "won",
    "lost":      "lost",
    "no response": "no_response",
}

def _map_status(deal: dict) -> str:
    # Stage is authoritative for Won/Lost
    stage = (deal.get("Stage") or "").strip().lower()
    if stage in STAGE_MAP:
        mapped = STAGE_MAP[stage]
        if mapped in ("won", "lost"):
            return mapped
    # Enquiry_Status for Quoted/Pending/Regretted
    enquiry = (deal.get("Enquiry_Status") or "").strip().lower()
    if enquiry in ENQUIRY_STATUS_MAP:
        return ENQUIRY_STATUS_MAP[enquiry]
    # Stage fallback for non-terminal states
    if stage in STAGE_MAP:
        return STAGE_MAP[stage]
    return "bid_sent"


REVERSE_MAP = {
    "won":         "Closed Won",
    "lost":        "Closed Lost",
    "quoted":      "Proposal/Price Quote",
    "bid_sent":    "Qualification",
    "no_response": "Qualification",
}


class ZohoPushRequest(BaseModel):
    stage:        Optional[str]   = None
    amount:       Optional[float] = None
    closing_date: Optional[str]   = None
    description:  Optional[str]   = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _fetch_page(token: str, page: int, since_iso: Optional[str]) -> list:
    """Fetch one page from Zoho. Called in parallel threads."""
    url = (f"https://www.zohoapis.{ZOHO_DC}/crm/v2/{ZOHO_MODULE}"
           f"?per_page=200&page={page}&sort_by=Modified_Time&sort_order=desc")
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Zoho-oauthtoken {token}")
    if since_iso:
        req.add_header("If-Modified-Since", since_iso)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        return data.get("data", []), data.get("info", {}).get("more_records", False)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return [], False
        raise


def _extract_row(deal: dict, div_map: dict) -> tuple:
    """Pure data extraction — no DB calls. Returns a tuple for bulk insert."""
    zoho_id   = str(deal.get("id", ""))
    deal_name = deal.get("Deal_Name") or ""
    client      = deal.get("Project_Name") or deal.get("Customer_Name") or deal.get("Contact_Person") or deal_name
    salesperson = deal.get("Salesperson") or ""
    if not salesperson and isinstance(deal.get("Owner"), dict):
        salesperson = deal["Owner"].get("name", "")
    division_raw = ", ".join(deal.get("BB_Division") or []) or deal.get("Team_Sub_Team") or ""
    first_div    = division_raw.split(",")[0].strip() if division_raw else ""
    div_entry    = div_map.get(first_div.upper()) or div_map.get(first_div)
    division_id  = div_entry[0] if div_entry else None
    division_label = div_entry[1] if div_entry else (first_div or None)

    amount       = deal.get("Enquiry_Value_in_AED") or deal.get("Budgetary_Quote_Value_AED") or deal.get("Customer_Quoted_Amount")
    lost_reason  = deal.get("Reason_For_Loss__s")
    bid_sent_date= deal.get("Bid_Submission_date") or deal.get("Inquiry_received_date")
    outcome_date_raw = deal.get("Customer_Order_Received_date") or deal.get("Bid_Closing_Date") or deal.get("Expected_Closing_Date")
    notes        = deal.get("Remarks") or deal.get("Enquiry_Description") or deal.get("Description") or ""
    our_status   = _map_status(deal)
    outcome_date = outcome_date_raw if our_status in ("won", "lost") else None
    order_val    = float(amount) if our_status == "won" and amount is not None else None

    return (zoho_id, division_id, division_label, our_status,
            amount, order_val,
            client or None, salesperson or None, lost_reason or None,
            notes or None, outcome_date, bid_sent_date, deal_name)


def _run_sync_background(since_iso: Optional[str], limit: int):
    """Runs in a background thread — parallel fetch + bulk upsert."""
    global _sync_state
    _sync_state["running"] = True
    _sync_state["result"] = None
    _sync_state["error"] = None

    db = None
    try:
        _check_configured()
        token = _refresh_access_token()

        # ── Step 1: fetch page 1 to learn total page count ──────────────
        first_batch, more = _fetch_page(token, 1, since_iso)
        if not first_batch:
            _sync_state["result"] = {"success": True, "fetched": 0, "total_in_db": 0, "errors": 0}
            return

        # Estimate remaining pages (200/page, up to limit)
        max_pages = min((limit // 200) + 1, 50)
        all_deals = list(first_batch)

        if more and max_pages > 1:
            # ── Step 2: fetch remaining pages in parallel (8 threads) ───
            with ThreadPoolExecutor(max_workers=8) as ex:
                futures = {ex.submit(_fetch_page, token, p, since_iso): p
                           for p in range(2, max_pages + 1)}
                for fut in as_completed(futures):
                    try:
                        batch, _ = fut.result()
                        if batch:
                            all_deals.extend(batch)
                        else:
                            break
                    except Exception:
                        pass

        # ── Step 3: pre-load division map once ──────────────────────────
        db = get_connection()
        cur = db.cursor()
        cur.execute("SELECT code, id, name FROM divisions")
        div_rows = cur.fetchall()
        # index by uppercase code and uppercase name
        div_map = {}
        for code, did, name in div_rows:
            div_map[code.upper()] = (did, name)
            div_map[name.upper()] = (did, name)

        # ── Step 4: extract all rows in Python (no DB per deal) ─────────
        rows = []
        errors = []
        for deal in all_deals:
            try:
                rows.append(_extract_row(deal, div_map))
            except Exception as e:
                errors.append({"zoho_id": str(deal.get("id", "")), "error": str(e)})

        # ── Step 5: bulk upsert with ON CONFLICT ────────────────────────
        if rows:
            cur.executemany("""
                INSERT INTO bids_tracking
                    (zoho_deal_id, division_id, division_label, status,
                     quotation_value, order_value,
                     client, salesperson_name, lost_reason, notes,
                     outcome_date, bid_sent_date, bid_ref)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::date,%s::date,%s)
                ON CONFLICT (zoho_deal_id) DO UPDATE SET
                    status          = EXCLUDED.status,
                    quotation_value = COALESCE(EXCLUDED.quotation_value, bids_tracking.quotation_value),
                    order_value     = COALESCE(EXCLUDED.order_value,     bids_tracking.order_value),
                    client          = COALESCE(EXCLUDED.client,          bids_tracking.client),
                    salesperson_name= COALESCE(EXCLUDED.salesperson_name,bids_tracking.salesperson_name),
                    division_id     = COALESCE(EXCLUDED.division_id,     bids_tracking.division_id),
                    division_label  = COALESCE(EXCLUDED.division_label,  bids_tracking.division_label),
                    lost_reason     = COALESCE(EXCLUDED.lost_reason,     bids_tracking.lost_reason),
                    notes           = COALESCE(EXCLUDED.notes,           bids_tracking.notes),
                    outcome_date    = COALESCE(EXCLUDED.outcome_date,    bids_tracking.outcome_date),
                    bid_sent_date   = COALESCE(EXCLUDED.bid_sent_date,   bids_tracking.bid_sent_date),
                    bid_ref         = COALESCE(EXCLUDED.bid_ref,         bids_tracking.bid_ref),
                    updated_at      = NOW()
            """, rows)

        cur.execute("SELECT COUNT(*) FROM bids_tracking")
        total = cur.fetchone()[0]

        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS zoho_sync_log (
                    id SERIAL PRIMARY KEY, synced_at TIMESTAMPTZ DEFAULT NOW(),
                    fetched INTEGER, created INTEGER, updated INTEGER,
                    skipped INTEGER, errors INTEGER, details JSONB)
            """)
            cur.execute("""
                INSERT INTO zoho_sync_log (fetched, created, updated, skipped, errors, details)
                VALUES (%s, 0, 0, 0, %s, %s)
            """, (len(all_deals), len(errors), json.dumps(errors[:20]) if errors else None))
        except Exception:
            pass

        db.commit()
        cur.close()
        _sync_state["result"] = {"success": True, "fetched": len(all_deals),
                                  "total_in_db": total, "errors": len(errors)}

    except Exception as e:
        _sync_state["error"] = str(e)
        if db:
            try: db.rollback()
            except: pass
    finally:
        _sync_state["running"] = False
        if db:
            try: db.close()
            except: pass


@router.post("/sync")
def sync_from_zoho(full: bool = Query(False), db=Depends(get_db)):
    """
    Launch Zoho sync in background. Returns immediately.
    Pass ?full=true to ignore last-sync time and re-fetch everything.
    """
    global _sync_state
    if _sync_state["running"]:
        return {"status": "already_running", "message": "Sync already in progress"}

    _check_configured()

    # Determine since timestamp for incremental sync
    since_iso = None
    if not full:
        try:
            cur = db.cursor()
            cur.execute("SELECT synced_at FROM zoho_sync_log ORDER BY synced_at DESC LIMIT 1")
            row = cur.fetchone()
            cur.close()
            if row and row[0]:
                since_iso = row[0].strftime("%a, %d %b %Y %H:%M:%S GMT")
        except Exception:
            pass

    _sync_state["running"] = True
    _sync_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _sync_state["result"] = None
    _sync_state["error"] = None

    t = threading.Thread(target=_run_sync_background, args=(since_iso, 10000), daemon=True)
    t.start()

    mode = "incremental" if since_iso else "full"
    return {"status": "started", "mode": mode, "since": since_iso}


@router.get("/sync/status")
def get_sync_status():
    """Poll this to know if a background sync is running and what the last result was."""
    return {
        "running":    _sync_state["running"],
        "started_at": _sync_state["started_at"],
        "result":     _sync_state["result"],
        "error":      _sync_state["error"],
    }


@router.get("/sync/log")
def get_sync_log(limit: int = Query(20, le=100), db=Depends(get_db)):
    cur = db.cursor()
    try:
        cur.execute("""
            SELECT id, synced_at, fetched, created, updated, skipped, errors
            FROM zoho_sync_log
            ORDER BY synced_at DESC
            LIMIT %s
        """, (limit,))
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            row = dict(zip(cols, r))
            if row.get("synced_at"):
                row["synced_at"] = row["synced_at"].isoformat()
            rows.append(row)
        return {"success": True, "log": rows}
    except Exception:
        return {"success": True, "log": []}
    finally:
        cur.close()


@router.post("/push/{bid_id}")
def push_bid_to_zoho(bid_id: int, req: ZohoPushRequest, db=Depends(get_db)):
    """Push a bid status change back to a Zoho Deal."""
    _check_configured()

    cur = db.cursor()
    cur.execute("SELECT zoho_deal_id, status, order_value FROM bids_tracking WHERE id = %s", (bid_id,))
    row = cur.fetchone()
    cur.close()

    if not row:
        raise HTTPException(status_code=404, detail="Bid not found")
    zoho_id, status, order_value = row
    if not zoho_id:
        raise HTTPException(status_code=400, detail="This bid has no linked Zoho Deal ID")

    token = _refresh_access_token()
    zoho_stage = req.stage or REVERSE_MAP.get(status, "Qualification")

    payload: dict = {"data": [{"id": zoho_id, "Stage": zoho_stage}]}
    if req.amount is not None:
        payload["data"][0]["Amount"] = req.amount
    if req.closing_date:
        payload["data"][0]["Closing_Date"] = req.closing_date
    if req.description:
        payload["data"][0]["Description"] = req.description

    url    = f"https://www.zohoapis.{ZOHO_DC}/crm/v2/{ZOHO_MODULE}"
    result = _zoho_request(url, token, method="PUT", data=payload)
    return {"success": True, "zoho_response": result}
