"""
routes/bids.py
Bid outcome tracking — status lifecycle: bid_sent → quoted → won | lost | no_response
Endpoints:
  GET    /bids/                   — list bids (filtered by role/division)
  POST   /bids/                   — create bid record
  PATCH  /bids/{bid_id}           — update status / outcome
  DELETE /bids/{bid_id}           — delete
  GET    /bids/stats              — conversion stats
  GET    /bids/by-salesperson     — breakdown per salesperson
  GET    /bids/by-inquiry/{id}    — bids for a specific RFQ
  PATCH  /bids/by-inquiry/{id}/status — quick status update from RFQ modal
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
from datetime import date
from database import get_db

router = APIRouter(prefix="/bids", tags=["Bids Tracking"])

VALID_STATUSES = {"bid_sent", "quoted", "won", "lost", "no_response"}

STATUS_LABELS = {
    "bid_sent":    "Bid Sent",
    "quoted":      "Quoted",
    "won":         "Won",
    "lost":        "Lost",
    "no_response": "No Response",
}


class BidCreate(BaseModel):
    inquiry_id:         Optional[str]   = None
    division_id:        Optional[int]   = None
    client:             Optional[str]   = None
    salesperson_name:   Optional[str]   = None
    bid_ref:            Optional[str]   = None
    status:             Optional[str]   = "bid_sent"
    quotation_value:    Optional[float] = None
    quotation_currency: Optional[str]   = "AED"
    order_value:        Optional[float] = None
    lost_reason:        Optional[str]   = None
    competitor_name:    Optional[str]   = None
    notes:              Optional[str]   = None
    zoho_deal_id:       Optional[str]   = None
    bid_sent_date:      Optional[date]  = None
    quoted_date:        Optional[date]  = None
    outcome_date:       Optional[date]  = None


class BidUpdate(BaseModel):
    status:             Optional[str]   = None
    quotation_value:    Optional[float] = None
    quotation_currency: Optional[str]   = None
    order_value:        Optional[float] = None
    lost_reason:        Optional[str]   = None
    competitor_name:    Optional[str]   = None
    notes:              Optional[str]   = None
    zoho_deal_id:       Optional[str]   = None
    bid_sent_date:      Optional[date]  = None
    quoted_date:        Optional[date]  = None
    outcome_date:       Optional[date]  = None
    salesperson_name:   Optional[str]   = None


def _serialize(row: dict) -> dict:
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            row[k] = v.isoformat()
        elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
            try:
                row[k] = float(v)
            except Exception:
                pass
    return row


ALL_ACCESS_ROLES = {"chairman", "gm", "manager", "developer"}

def _build_where(role, ids, salesperson_name):
    if role == "salesperson" and salesperson_name:
        return "WHERE b.salesperson_name = %s", [salesperson_name]
    elif role in ALL_ACCESS_ROLES or not ids:
        return "", []
    else:
        ph = ",".join(["%s"] * len(ids))
        return f"WHERE b.division_id IN ({ph})", list(ids)


@router.get("/")
def get_bids(
    role:             str           = Query(...),
    division_ids:     Optional[str] = Query(None),
    salesperson_name: Optional[str] = Query(None),
    status:           Optional[str] = Query(None),
    db=Depends(get_db),
):
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []
        where, params = _build_where(role, ids, salesperson_name)

        if status and status in VALID_STATUSES:
            connector = "AND" if where else "WHERE"
            where += f" {connector} b.status = %s"
            params.append(status)

        cursor.execute(f"""
            SELECT b.*, d.name AS division_name, d.code AS division_code
            FROM bids_tracking b
            LEFT JOIN divisions d ON b.division_id = d.id
            {where}
            ORDER BY b.created_at DESC
        """, params)

        cols = [d[0] for d in cursor.description]
        rows = [_serialize(dict(zip(cols, r))) for r in cursor.fetchall()]
        return {"success": True, "bids": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.post("/")
def create_bid(req: BidCreate, db=Depends(get_db)):
    cursor = db.cursor()
    try:
        if req.status and req.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}")

        cursor.execute("""
            INSERT INTO bids_tracking
                (inquiry_id, division_id, client, salesperson_name, bid_ref,
                 status, quotation_value, quotation_currency, order_value,
                 lost_reason, competitor_name, notes, zoho_deal_id,
                 bid_sent_date, quoted_date, outcome_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            req.inquiry_id, req.division_id, req.client, req.salesperson_name,
            req.bid_ref, req.status or "bid_sent", req.quotation_value,
            req.quotation_currency or "AED", req.order_value, req.lost_reason,
            req.competitor_name, req.notes, req.zoho_deal_id,
            req.bid_sent_date, req.quoted_date, req.outcome_date,
        ))
        bid_id = cursor.fetchone()[0]

        # Sync status to inquiry_master
        if req.inquiry_id and req.status:
            cursor.execute("""
                UPDATE inquiry_master
                SET bid_status   = %s,
                    outcome_date = %s,
                    order_value  = %s,
                    zoho_deal_id = %s,
                    updated_at   = NOW()
                WHERE inquiry_id = %s
            """, (req.status, req.outcome_date, req.order_value, req.zoho_deal_id, req.inquiry_id))

            # Also update pipeline_decisions outcome if won/lost
            if req.status in ("won", "lost"):
                cursor.execute("""
                    UPDATE pipeline_decisions
                    SET outcome = %s, outcome_date = NOW()
                    WHERE inquiry_id = %s AND outcome IS NULL
                """, (req.status, req.inquiry_id))

        db.commit()
        return {"success": True, "bid_id": bid_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.patch("/{bid_id}")
def update_bid(bid_id: int, req: BidUpdate, db=Depends(get_db)):
    cursor = db.cursor()
    try:
        if req.status and req.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}")

        updates = {k: v for k, v in req.dict(exclude_none=True).items()}
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        updates["updated_at"] = "NOW()"
        set_parts, params = [], []
        for k, v in updates.items():
            if v == "NOW()":
                set_parts.append(f"{k} = NOW()")
            else:
                set_parts.append(f"{k} = %s")
                params.append(v)

        params.append(bid_id)
        cursor.execute(
            f"UPDATE bids_tracking SET {', '.join(set_parts)} WHERE id = %s RETURNING inquiry_id",
            params,
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bid not found")

        inquiry_id = row[0]

        # Sync status change back to inquiry_master
        if inquiry_id and req.status:
            cursor.execute("""
                UPDATE inquiry_master
                SET bid_status   = %s,
                    outcome_date = %s,
                    order_value  = %s,
                    updated_at   = NOW()
                WHERE inquiry_id = %s
            """, (req.status, req.outcome_date, req.order_value, inquiry_id))

            if req.status in ("won", "lost"):
                cursor.execute("""
                    UPDATE pipeline_decisions
                    SET outcome = %s, outcome_date = NOW()
                    WHERE inquiry_id = %s AND outcome IS NULL
                """, (req.status, inquiry_id))

        db.commit()
        return {"success": True, "message": "Bid updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.delete("/{bid_id}")
def delete_bid(bid_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM bids_tracking WHERE id = %s RETURNING id", (bid_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Bid not found")
        db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/stats")
def get_bids_stats(
    role:             str           = Query(...),
    division_ids:     Optional[str] = Query(None),
    salesperson_name: Optional[str] = Query(None),
    db=Depends(get_db),
):
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []
        where, params = _build_where(role, ids, salesperson_name)

        cursor.execute(f"""
            SELECT
                COUNT(*)                                              AS total,
                COUNT(*) FILTER (WHERE status = 'bid_sent')          AS bid_sent,
                COUNT(*) FILTER (WHERE status = 'quoted')            AS quoted,
                COUNT(*) FILTER (WHERE status = 'won')               AS won,
                COUNT(*) FILTER (WHERE status = 'lost')              AS lost,
                COUNT(*) FILTER (WHERE status = 'no_response')       AS no_response,
                COALESCE(SUM(quotation_value), 0)                    AS total_quoted_value,
                COALESCE(SUM(order_value) FILTER (WHERE status='won'), 0) AS total_won_value
            FROM bids_tracking b
            {where}
        """, params)

        cols = [d[0] for d in cursor.description]
        stats = dict(zip(cols, cursor.fetchone()))
        for k, v in stats.items():
            if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                stats[k] = float(v)

        total = stats.get("total", 0)
        won   = stats.get("won", 0)
        lost  = stats.get("lost", 0)
        stats["conversion_rate"] = round(won / total * 100, 1) if total > 0 else 0.0
        stats["win_vs_lost_rate"] = round(won / (won + lost) * 100, 1) if (won + lost) > 0 else 0.0

        return {"success": True, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/by-salesperson")
def bids_by_salesperson(
    role:         str           = Query(...),
    division_ids: Optional[str] = Query(None),
    db=Depends(get_db),
):
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []
        where, params = _build_where(role, ids, None)

        cursor.execute(f"""
            SELECT
                b.salesperson_name,
                d.name  AS division_name,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE b.status = 'won')    AS won,
                COUNT(*) FILTER (WHERE b.status = 'lost')   AS lost,
                COUNT(*) FILTER (WHERE b.status = 'quoted') AS quoted,
                COALESCE(SUM(b.quotation_value), 0)          AS total_quoted_value,
                COALESCE(SUM(b.order_value) FILTER (WHERE b.status='won'), 0) AS total_won_value
            FROM bids_tracking b
            LEFT JOIN divisions d ON b.division_id = d.id
            {where}
            GROUP BY b.salesperson_name, d.name
            ORDER BY total DESC
        """, params)

        cols = [d[0] for d in cursor.description]
        data = [dict(zip(cols, r)) for r in cursor.fetchall()]
        for row in data:
            row["total_quoted_value"] = float(row["total_quoted_value"])
            row["total_won_value"]    = float(row["total_won_value"])
            total = row["total"] or 1
            row["conversion_rate"] = round(row["won"] / total * 100, 1)

        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/by-inquiry/{inquiry_id}")
def get_bids_for_inquiry(inquiry_id: str, db=Depends(get_db)):
    """Get all bid records for a specific RFQ — used by the RFQ detail modal."""
    cursor = db.cursor()
    try:
        cursor.execute("""
            SELECT b.*, d.name AS division_name
            FROM bids_tracking b
            LEFT JOIN divisions d ON b.division_id = d.id
            WHERE b.inquiry_id = %s
            ORDER BY b.created_at DESC
        """, (inquiry_id,))
        cols = [d[0] for d in cursor.description]
        rows = [_serialize(dict(zip(cols, r))) for r in cursor.fetchall()]
        return {"success": True, "bids": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.patch("/by-inquiry/{inquiry_id}/status")
def update_inquiry_bid_status(inquiry_id: str, req: BidUpdate, db=Depends(get_db)):
    """
    Quick status update from the RFQ modal.
    Creates a bid record if none exists, otherwise updates the latest one.
    Also syncs status to inquiry_master and pipeline_decisions.
    """
    cursor = db.cursor()
    try:
        if req.status and req.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}")

        # Check if a bid record exists
        cursor.execute(
            "SELECT id FROM bids_tracking WHERE inquiry_id = %s ORDER BY created_at DESC LIMIT 1",
            (inquiry_id,)
        )
        existing = cursor.fetchone()

        if existing:
            bid_id = existing[0]
            updates = {k: v for k, v in req.dict(exclude_none=True).items()}
            set_parts, params = ["updated_at = NOW()"], []
            for k, v in updates.items():
                set_parts.append(f"{k} = %s")
                params.append(v)
            params.append(bid_id)
            cursor.execute(
                f"UPDATE bids_tracking SET {', '.join(set_parts)} WHERE id = %s",
                params,
            )
        else:
            # Pull client from inquiry_master to auto-fill
            cursor.execute("SELECT client, division_id FROM inquiry_master WHERE inquiry_id = %s", (inquiry_id,))
            inq = cursor.fetchone()
            cursor.execute("""
                INSERT INTO bids_tracking
                    (inquiry_id, division_id, client, status, quotation_value,
                     order_value, lost_reason, notes, outcome_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                inquiry_id,
                inq[1] if inq else None,
                inq[0] if inq else None,
                req.status or "bid_sent",
                req.quotation_value, req.order_value,
                req.lost_reason, req.notes, req.outcome_date,
            ))

        # Sync to inquiry_master
        if req.status:
            cursor.execute("""
                UPDATE inquiry_master
                SET bid_status   = %s,
                    outcome_date = %s,
                    order_value  = %s,
                    updated_at   = NOW()
                WHERE inquiry_id = %s
            """, (req.status, req.outcome_date, req.order_value, inquiry_id))

            # Propagate won/lost to pipeline_decisions
            if req.status in ("won", "lost"):
                cursor.execute("""
                    UPDATE pipeline_decisions
                    SET outcome = %s, outcome_date = NOW()
                    WHERE inquiry_id = %s AND outcome IS NULL
                """, (req.status, inquiry_id))

        db.commit()
        return {"success": True, "status": req.status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
