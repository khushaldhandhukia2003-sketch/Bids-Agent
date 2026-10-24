from fastapi import APIRouter, HTTPException, Depends, Query
from database import get_db
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/quotations", tags=["Quotations"])


@router.get("/")
def get_quotations(
    role: str = Query(...),
    division_ids: Optional[str] = Query(None),
    db=Depends(get_db)
):
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []

        if role == "chairman" or not ids:
            cursor.execute("""
                SELECT q.*, d.name AS division_name, d.code AS division_code,
                       v.name AS vendor_name
                FROM quotations q
                LEFT JOIN divisions d ON q.division_id = d.id
                LEFT JOIN vendors v ON q.vendor_id = v.id
                ORDER BY q.id DESC
            """)
        else:
            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(f"""
                SELECT q.*, d.name AS division_name, d.code AS division_code,
                       v.name AS vendor_name
                FROM quotations q
                LEFT JOIN divisions d ON q.division_id = d.id
                LEFT JOIN vendors v ON q.vendor_id = v.id
                WHERE q.division_id IN ({placeholders})
                ORDER BY q.id DESC
            """, ids)

        columns = [desc[0] for desc in cursor.description]
        quotations = []
        for row in cursor.fetchall():
            q = dict(zip(columns, row))
            for k, v in q.items():
                if hasattr(v, 'isoformat'):
                    q[k] = v.isoformat()
                if hasattr(v, '__float__'):
                    try: q[k] = float(v)
                    except: pass
            quotations.append(q)

        return {"success": True, "quotations": quotations, "count": len(quotations)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/stats")
def get_quotation_stats(
    role: str = Query(...),
    division_ids: Optional[str] = Query(None),
    db=Depends(get_db)
):
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []

        if role == "chairman" or not ids:
            cursor.execute("SELECT COUNT(*) FROM quotations")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM quotations WHERE status='won'")
            won = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM quotations WHERE status='lost'")
            lost = cursor.fetchone()[0]
            cursor.execute("SELECT COALESCE(SUM(quotation_amount),0) FROM quotations WHERE status='won'")
            won_value = cursor.fetchone()[0]
        else:
            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(f"SELECT COUNT(*) FROM quotations WHERE division_id IN ({placeholders})", ids)
            total = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM quotations WHERE division_id IN ({placeholders}) AND status='won'", ids)
            won = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM quotations WHERE division_id IN ({placeholders}) AND status='lost'", ids)
            lost = cursor.fetchone()[0]
            cursor.execute(f"SELECT COALESCE(SUM(quotation_amount),0) FROM quotations WHERE division_id IN ({placeholders}) AND status='won'", ids)
            won_value = cursor.fetchone()[0]

        return {
            "success": True,
            "stats": {
                "total":     total,
                "won":       won,
                "lost":      lost,
                "pending":   total - won - lost,
                "won_value": float(won_value or 0),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()