"""
routes/users.py

User management — list, create, update, delete users and their division access.
Only callable by chairman role (enforced on the frontend; backend trusts the call).

GET    /api/users               — list all users with their divisions
POST   /api/users               — create a new user
PUT    /api/users/{id}          — update name / password / role
DELETE /api/users/{id}          — delete a user
PUT    /api/users/{id}/divisions — replace a user's division assignments
GET    /api/divisions            — list all canonical divisions
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from database import get_db

router = APIRouter(tags=["Users"])


# ── Schemas ──────────────────────────────────────────────────────

class CreateUser(BaseModel):
    name: str
    username: str
    password: str
    email: Optional[str] = ""
    role: str = "procurement"
    division_ids: List[int] = []

class UpdateUser(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None

class UpdateDivisions(BaseModel):
    division_ids: List[int]


# ── Helpers ──────────────────────────────────────────────────────

def _get_user_with_divisions(cur, user_id):
    cur.execute("""
        SELECT u.id, u.name, u.username, u.password, u.role,
               COALESCE(
                   JSON_AGG(
                       JSON_BUILD_OBJECT('id', d.id, 'name', d.name, 'code', d.code)
                       ORDER BY d.name
                   ) FILTER (WHERE d.id IS NOT NULL),
                   '[]'
               ) AS divisions
        FROM users u
        LEFT JOIN user_divisions ud ON u.id = ud.user_id
        LEFT JOIN divisions d ON ud.division_id = d.id
        WHERE u.id = %s
        GROUP BY u.id, u.name, u.username, u.password, u.role
    """, (user_id,))
    row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "name": row[1], "username": row[2],
        "password": row[3], "role": row[4], "divisions": row[5]
    }


# ── Endpoints ─────────────────────────────────────────────────────

@router.get("/users")
def list_users(db=Depends(get_db)):
    cur = db.cursor()
    try:
        cur.execute("""
            SELECT u.id, u.name, u.username, u.password, u.role,
                   COALESCE(
                       JSON_AGG(
                           JSON_BUILD_OBJECT('id', d.id, 'name', d.name, 'code', d.code)
                           ORDER BY d.name
                       ) FILTER (WHERE d.id IS NOT NULL),
                       '[]'
                   ) AS divisions
            FROM users u
            LEFT JOIN user_divisions ud ON u.id = ud.user_id
            LEFT JOIN divisions d ON ud.division_id = d.id
            GROUP BY u.id, u.name, u.username, u.password, u.role
            ORDER BY u.role, u.name
        """)
        rows = cur.fetchall()
        return {"success": True, "users": [
            {"id": r[0], "name": r[1], "username": r[2],
             "password": r[3], "role": r[4], "divisions": r[5]}
            for r in rows
        ]}
    finally:
        cur.close()


@router.post("/users")
def create_user(body: CreateUser, db=Depends(get_db)):
    cur = db.cursor()
    try:
        # Check username unique
        cur.execute("SELECT id FROM users WHERE username = %s", (body.username,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Username already exists")

        cur.execute(
            "INSERT INTO users (name, username, password, email, role) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (body.name.strip(), body.username.strip(), body.password, body.email or "", body.role)
        )
        new_id = cur.fetchone()[0]

        for did in body.division_ids:
            cur.execute(
                "INSERT INTO user_divisions (user_id, division_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (new_id, did)
            )

        db.commit()
        user = _get_user_with_divisions(cur, new_id)
        return {"success": True, "user": user}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UpdateUser, db=Depends(get_db)):
    cur = db.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="User not found")

        fields, params = [], []
        if body.name is not None:
            fields.append("name = %s"); params.append(body.name.strip())
        if body.password is not None:
            fields.append("password = %s"); params.append(body.password)
        if body.role is not None:
            fields.append("role = %s"); params.append(body.role)

        if fields:
            params.append(user_id)
            cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = %s", params)

        db.commit()
        user = _get_user_with_divisions(cur, user_id)
        return {"success": True, "user": user}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db=Depends(get_db)):
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM user_divisions WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="User not found")
        db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()


@router.put("/users/{user_id}/divisions")
def update_user_divisions(user_id: int, body: UpdateDivisions, db=Depends(get_db)):
    cur = db.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="User not found")

        # Replace all division assignments
        cur.execute("DELETE FROM user_divisions WHERE user_id = %s", (user_id,))
        for did in body.division_ids:
            cur.execute(
                "INSERT INTO user_divisions (user_id, division_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, did)
            )
        db.commit()
        user = _get_user_with_divisions(cur, user_id)
        return {"success": True, "user": user}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()


@router.get("/divisions")
def list_divisions(db=Depends(get_db)):
    cur = db.cursor()
    try:
        cur.execute("SELECT id, name, code FROM divisions ORDER BY name")
        rows = cur.fetchall()
        return {"success": True, "divisions": [
            {"id": r[0], "name": r[1], "code": r[2]} for r in rows
        ]}
    finally:
        cur.close()
