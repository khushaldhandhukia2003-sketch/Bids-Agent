"""
routes/history.py

Activity log — records key procurement events and exposes them as a feed.

POST  (internal) log_activity(...)   — called by other routes, not an endpoint
GET   /api/history                   — paginated activity feed (filterable by user/role/event_type)
DELETE /api/history/{id}             — delete one entry (admin)
GET   /api/history/users             — list of distinct users who appear in the log
"""

import json
from fastapi import APIRouter, Depends, Query
from database import get_db, get_connection

router = APIRouter(tags=["History"])

# ── Ensure columns exist (runs once on first import) ────────────
def _ensure_columns():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            ALTER TABLE activity_log
                ADD COLUMN IF NOT EXISTS username  TEXT,
                ADD COLUMN IF NOT EXISTS user_role TEXT
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  history column migration: {e}")

try:
    _ensure_columns()
except Exception:
    pass


# ── Internal helper called by other routes ──────────────────────

def log_activity(
    event_type: str,
    title:      str,
    detail:     str  = "",
    meta:       dict = None,
    db=None,
    username:   str  = None,
    user_role:  str  = None,
):
    """
    Write one activity_log row.
    event_type: 'rfq_import' | 'vendor_discovery' | 'vendor_import'
    Pass username + user_role so entries are attributable to a person.
    db: an open psycopg2 connection (already has a transaction open is fine)
    """
    own_conn = db is None
    conn = get_connection() if own_conn else db
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO activity_log (event_type, title, detail, meta, username, user_role)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (event_type, title[:255], detail[:1000],
             json.dumps(meta or {}), username, user_role),
        )
        if own_conn:
            conn.commit()
        cur.close()
    except Exception as e:
        print(f"⚠️  log_activity failed: {e}")
        if own_conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass


# ── Endpoints ───────────────────────────────────────────────────

@router.get("/history/users")
def get_history_users(db=Depends(get_db)):
    """Distinct usernames that appear in the log — for filter dropdowns."""
    cursor = db.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT username, user_role
            FROM activity_log
            WHERE username IS NOT NULL
            ORDER BY username
        """)
        rows = cursor.fetchall()
        return {"success": True, "users": [{"username": r[0], "role": r[1]} for r in rows]}
    finally:
        cursor.close()


@router.get("/history")
def get_history(
    limit:      int = Query(50, ge=1, le=200),
    offset:     int = Query(0, ge=0),
    event_type: str = Query(None),
    username:   str = Query(None),
    user_role:  str = Query(None),
    db=Depends(get_db),
):
    cursor = db.cursor()
    try:
        conditions = []
        params     = []
        if event_type:
            conditions.append("event_type = %s"); params.append(event_type)
        if username:
            conditions.append("username = %s");   params.append(username)
        if user_role:
            conditions.append("user_role = %s");  params.append(user_role)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        cursor.execute(
            f"""
            SELECT id, event_type, title, detail, meta, created_at, username, user_role
            FROM activity_log
            {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows   = cursor.fetchall()
        events = []
        for row in rows:
            meta_val = row[4]
            if isinstance(meta_val, str):
                try:
                    meta_val = json.loads(meta_val)
                except Exception:
                    meta_val = {}
            events.append({
                "id":         row[0],
                "event_type": row[1],
                "title":      row[2],
                "detail":     row[3],
                "meta":       meta_val or {},
                "created_at": row[5].isoformat() if row[5] else None,
                "username":   row[6],
                "user_role":  row[7],
            })

        cursor.execute(f"SELECT COUNT(*) FROM activity_log {where}", params)
        total = cursor.fetchone()[0]
        return {"success": True, "events": events, "total": total}
    finally:
        cursor.close()


@router.delete("/history/{entry_id}")
def delete_history_entry(entry_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM activity_log WHERE id = %s RETURNING id", (entry_id,))
        row = cursor.fetchone()
        db.commit()
        if not row:
            return {"success": False, "detail": "Not found"}
        return {"success": True}
    finally:
        cursor.close()
