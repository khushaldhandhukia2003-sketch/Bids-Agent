from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(data: LoginRequest, db=Depends(get_db)):
    cursor = db.cursor()
    try:
        # Fetch user with their assigned divisions
        cursor.execute(
            """
            SELECT 
                u.id, 
                u.name, 
                u.username, 
                u.role,
                COALESCE(
                    JSON_AGG(
                        JSON_BUILD_OBJECT('id', d.id, 'name', d.name, 'code', d.code)
                        ORDER BY d.id
                    ) FILTER (WHERE d.id IS NOT NULL),
                    '[]'
                ) AS divisions
            FROM users u
            LEFT JOIN user_divisions ud ON u.id = ud.user_id
            LEFT JOIN divisions d ON ud.division_id = d.id
            WHERE u.username = %s AND u.password = %s
            GROUP BY u.id, u.name, u.username, u.role
            """,
            (data.username, data.password)
        )
        user = cursor.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        user_data = {
            "id": user[0],
            "name": user[1],
            "username": user[2],
            "role": user[3],
            # Chairman gets empty list [] → frontend treats as "sees all"
            "divisions": user[4],
            "division_ids": [d["id"] for d in user[4]]
        }

        return {"success": True, "user": user_data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()