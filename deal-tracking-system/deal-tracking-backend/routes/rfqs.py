from fastapi import APIRouter, HTTPException, Depends, Query
from database import get_db
from typing import Optional, List

router = APIRouter(prefix="/rfqs", tags=["RFQs"])


@router.get("/divisions/all")
def get_all_divisions(db=Depends(get_db)):
    """Returns all divisions (id, name, code) for dropdowns."""
    cursor = db.cursor()
    try:
        cursor.execute("SELECT id, name, code FROM divisions ORDER BY id")
        rows = cursor.fetchall()
        return {"divisions": [{"id": r[0], "name": r[1], "code": r[2]} for r in rows]}
    finally:
        cursor.close()


def build_division_filter(role: str, division_ids: List[int]):
    """
    Chairman (role='chairman') or empty division_ids → sees ALL
    GM/Manager with assigned divisions → filtered by their divisions
    """
    if role == "chairman" or not division_ids:
        return "", []
    
    placeholders = ",".join(["%s"] * len(division_ids))
    return f"WHERE r.division_id IN ({placeholders})", division_ids


@router.get("/")
def get_rfqs(
    role: str = Query(...),
    division_ids: Optional[str] = Query(None),  # comma-separated: "1,2,3"
    db=Depends(get_db)
):
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []
        where_clause, params = build_division_filter(role, ids)

        # inquiry_master is the live RFQ source
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []

        if role == "chairman" or not ids:
            cursor.execute("""
                SELECT
                    im.id,
                    im.inquiry_id       AS enquiry_ref_no,
                    im.client,
                    d.name              AS division_name,
                    d.code              AS division_code,
                    im.closing_date,
                    im.total_items,
                    im.created_at,
                    NULL                AS status,
                    im.division_id,
                    im.notes            AS description
                FROM inquiry_master im
                LEFT JOIN divisions d ON d.id = im.division_id
                WHERE im.is_draft IS NOT TRUE
                ORDER BY im.id DESC
            """)
        else:
            ph = ",".join(["%s"] * len(ids))
            cursor.execute(f"""
                SELECT
                    im.id,
                    im.inquiry_id       AS enquiry_ref_no,
                    im.client,
                    d.name              AS division_name,
                    d.code              AS division_code,
                    im.closing_date,
                    im.total_items,
                    im.created_at,
                    NULL                AS status,
                    im.division_id,
                    im.notes            AS description
                FROM inquiry_master im
                LEFT JOIN divisions d ON d.id = im.division_id
                WHERE im.is_draft IS NOT TRUE
                  AND (im.division_id IN ({ph}) OR im.division_id IS NULL)
                ORDER BY im.id DESC
            """, ids)

        columns = [desc[0] for desc in cursor.description]
        rfqs = [dict(zip(columns, row)) for row in cursor.fetchall()]

        # Convert datetime to string for JSON
        for rfq in rfqs:
            for key, val in rfq.items():
                if hasattr(val, 'isoformat'):
                    rfq[key] = val.isoformat()

        return {"success": True, "rfqs": rfqs, "count": len(rfqs)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/vendors")
def get_vendors(
    role: str = Query(...),
    division_ids: Optional[str] = Query(None),
    db=Depends(get_db)
):
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []

        # Use vendors_master as the primary source (382 enriched vendors)
        cursor.execute("""
            SELECT id, vendor_name AS name, email, phone, country, city,
                   website, brands, source, created_at
            FROM vendors_master
            ORDER BY id DESC
        """)

        columns = [desc[0] for desc in cursor.description]
        vendors = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return {"success": True, "vendors": vendors, "count": len(vendors)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/stats")
def get_stats(
    role: str = Query(...),
    division_ids: Optional[str] = Query(None),
    db=Depends(get_db)
):
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []
        where_clause, params = build_division_filter(role, ids)

        # Total RFQs — inquiry_master filtered by division
        try:
            if role == "chairman" or not ids:
                cursor.execute("SELECT COUNT(*) FROM inquiry_master")
            else:
                ph2 = ",".join(["%s"] * len(ids))
                cursor.execute(f"SELECT COUNT(*) FROM inquiry_master WHERE division_id IN ({ph2})", ids)
            total_rfqs = cursor.fetchone()[0]
        except Exception:
            cursor.execute(f"SELECT COUNT(*) FROM rfqs r {where_clause}", params)
            total_rfqs = cursor.fetchone()[0]

        # Total Vendors — vendors_master is the enriched source
        try:
            cursor.execute("SELECT COUNT(*) FROM vendors_master")
            total_vendors = cursor.fetchone()[0]
        except Exception:
            cursor.execute("SELECT COUNT(*) FROM vendors")
            total_vendors = cursor.fetchone()[0]

        # Total Items — inquiry_line_items is the live source
        try:
            cursor.execute("SELECT COUNT(*) FROM inquiry_line_items")
            total_items = cursor.fetchone()[0]
        except Exception:
            cursor.execute(f"""
                SELECT COUNT(*) FROM rfq_items ri
                JOIN rfqs r ON r.id = ri.rfq_id
                {where_clause}
            """, params)
            total_items = cursor.fetchone()[0]

        total_divisions = len(ids) if ids else 11

        return {
            "success": True,
            "stats": {
                "total_rfqs": total_rfqs,
                "total_vendors": total_vendors,
                "total_items": total_items,
                "total_divisions": total_divisions
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/my-divisions")
def get_my_divisions(
    role: str = Query(...),
    division_ids: Optional[str] = Query(None),
    db=Depends(get_db)
):
    """Returns division breakdown with RFQ counts for the dashboard sidebar"""
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []

        if role == "chairman" or not ids:
            cursor.execute("""
                SELECT d.id, d.name, d.code, COUNT(im.id) as rfq_count
                FROM divisions d
                LEFT JOIN inquiry_master im ON im.division_id = d.id AND im.is_draft IS NOT TRUE
                GROUP BY d.id, d.name, d.code
                ORDER BY d.id
            """)
        else:
            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(f"""
                SELECT d.id, d.name, d.code, COUNT(im.id) as rfq_count
                FROM divisions d
                LEFT JOIN inquiry_master im ON im.division_id = d.id AND im.is_draft IS NOT TRUE
                WHERE d.id IN ({placeholders})
                GROUP BY d.id, d.name, d.code
                ORDER BY d.id
            """, ids)

        columns = [desc[0] for desc in cursor.description]
        divisions = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return {"success": True, "divisions": divisions}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/inquiry/{inquiry_id}")
def get_inquiry_detail(inquiry_id: str, db=Depends(get_db)):
    """Returns full detail of one inquiry plus its line items."""
    cursor = db.cursor()
    try:
        cursor.execute("""
            SELECT im.*, d.name AS division_name
            FROM inquiry_master im
            LEFT JOIN divisions d ON d.id = im.division_id
            WHERE im.inquiry_id = %s
        """, (inquiry_id,))
        cols = [d[0] for d in cursor.description]
        row  = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        inquiry = dict(zip(cols, row))
        for k, v in inquiry.items():
            if hasattr(v, 'isoformat'):
                inquiry[k] = v.isoformat()

        cursor.execute("""
            SELECT id, line_ref, description, quantity, unit, category,
                   channel_codes, status, suppliers_found, new_vendors,
                   rfq_count, created_at
            FROM inquiry_line_items
            WHERE inquiry_id = %s
            ORDER BY id
        """, (inquiry_id,))
        item_cols = [d[0] for d in cursor.description]
        items = []
        for r in cursor.fetchall():
            item = dict(zip(item_cols, r))
            for k, v in item.items():
                if hasattr(v, 'isoformat'):
                    item[k] = v.isoformat()
            items.append(item)

        # If no line items were saved but notes contain a description, surface it
        if not items and inquiry.get("notes"):
            items = [{"id": None, "line_ref": "1", "description": inquiry["notes"],
                      "quantity": "", "unit": "", "category": "", "channel_codes": None,
                      "status": None, "suppliers_found": None, "new_vendors": None,
                      "rfq_count": None, "created_at": None}]

        return {"success": True, "inquiry": inquiry, "items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.put("/inquiry/{inquiry_id}")
def update_inquiry(inquiry_id: str, payload: dict, db=Depends(get_db)):
    """Update inquiry header fields and/or line items."""
    cursor = db.cursor()
    try:
        # Update inquiry_master header
        header = payload.get("inquiry", {})
        new_id = header.pop("new_inquiry_id", None)
        allowed = ["client", "division_id", "notes", "closing_date", "delivery", "team"]
        updates = {k: v for k, v in header.items() if k in allowed}
        if updates:
            set_clause = ", ".join(f"{k} = %s" for k in updates)
            cursor.execute(
                f"UPDATE inquiry_master SET {set_clause} WHERE inquiry_id = %s",
                list(updates.values()) + [inquiry_id]
            )
        # Rename inquiry_id if changed (FK-safe: copy row → update children → delete old)
        if new_id and new_id != inquiry_id:
            cursor.execute("""
                INSERT INTO inquiry_master (inquiry_id, client, delivery, notes, total_items, division_id, is_draft, created_at, closing_date)
                SELECT %s, client, delivery, notes, total_items, division_id, is_draft, created_at, closing_date
                FROM inquiry_master WHERE inquiry_id = %s
                ON CONFLICT (inquiry_id) DO NOTHING
            """, (new_id, inquiry_id))
            cursor.execute("UPDATE inquiry_line_items SET inquiry_id = %s WHERE inquiry_id = %s", (new_id, inquiry_id))
            cursor.execute("UPDATE discovered_vendors  SET inquiry_id = %s WHERE inquiry_id = %s", (new_id, inquiry_id))
            cursor.execute("UPDATE inquiry_history     SET inquiry_id = %s WHERE inquiry_id = %s", (new_id, inquiry_id))
            cursor.execute("DELETE FROM inquiry_master WHERE inquiry_id = %s", (inquiry_id,))
            inquiry_id = new_id

        # Update existing line items
        for item in payload.get("items", []):
            item_id = item.get("id")
            if not item_id:
                continue
            item_allowed = ["description", "quantity", "unit", "category", "status", "channel_codes"]
            item_updates = {k: v for k, v in item.items() if k in item_allowed}
            if item_updates:
                set_clause = ", ".join(f"{k} = %s" for k in item_updates)
                cursor.execute(
                    f"UPDATE inquiry_line_items SET {set_clause} WHERE id = %s AND inquiry_id = %s",
                    list(item_updates.values()) + [item_id, inquiry_id]
                )

        # Insert new line items
        for item in payload.get("new_items", []):
            cursor.execute("""
                INSERT INTO inquiry_line_items (inquiry_id, description, quantity, unit, category, status)
                VALUES (%s, %s, %s, %s, %s, 'pending')
            """, (inquiry_id, item.get("description", ""), item.get("quantity", ""),
                  item.get("unit", ""), item.get("category", "")))

        # Delete line items
        for item_id in payload.get("deleted_item_ids", []):
            cursor.execute("DELETE FROM inquiry_line_items WHERE id = %s AND inquiry_id = %s", (item_id, inquiry_id))

        # Update existing vendors
        for v in payload.get("vendors", []):
            name = v.get("name") or v.get("vendor_name")
            if not name:
                continue
            v_allowed = ["email", "phone", "website", "country", "city", "brands"]
            v_updates = {k: v[k] for k in v_allowed if k in v}
            if v_updates:
                set_clause = ", ".join(f"{k} = %s" for k in v_updates)
                cursor.execute(
                    f"UPDATE discovered_vendors SET {set_clause} WHERE vendor_name = %s AND inquiry_id = %s",
                    list(v_updates.values()) + [name, inquiry_id]
                )

        # Insert new vendors
        for v in payload.get("new_vendors", []):
            cursor.execute("""
                INSERT INTO discovered_vendors (vendor_name, email, phone, website, country, city, brands, source, inquiry_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'manual', %s)
                ON CONFLICT DO NOTHING
            """, (v.get("name", ""), v.get("email", ""), v.get("phone", ""),
                  v.get("website", ""), v.get("country", ""), v.get("city", ""),
                  v.get("brands", ""), inquiry_id))

        # Delete vendors
        for name in payload.get("deleted_vendor_names", []):
            cursor.execute("DELETE FROM discovered_vendors WHERE vendor_name = %s AND inquiry_id = %s", (name, inquiry_id))

        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/inquiry/{inquiry_id}/vendors")
def get_inquiry_vendors(inquiry_id: str, db=Depends(get_db)):
    """Returns vendors discovered for a given inquiry.
    Primary source: discovered_vendors (populated on Save).
    Fallback: vendor names from inquiry_line_items / inquiry_history looked up in vendors_master.
    """
    cursor = db.cursor()
    try:
        # Primary: discovered_vendors (most complete — email, score, etc.)
        cursor.execute("""
            SELECT id, vendor_name AS name, country, city, email, phone, website,
                   brands, source, confidence_score
            FROM discovered_vendors
            WHERE inquiry_id = %s
            ORDER BY confidence_score DESC NULLS LAST, vendor_name
        """, (inquiry_id,))
        cols = [d[0] for d in cursor.description]
        vendors = [dict(zip(cols, row)) for row in cursor.fetchall()]

        if not vendors:
            # Fallback 1: multi-item — collect vendor names from inquiry_line_items
            cursor.execute("""
                SELECT suppliers_found, new_vendors
                FROM inquiry_line_items
                WHERE inquiry_id = %s AND (suppliers_found IS NOT NULL OR new_vendors IS NOT NULL)
            """, (inquiry_id,))
            name_set = set()
            for row in cursor.fetchall():
                for field in (row[0], row[1]):
                    if field:
                        for n in field.split(","):
                            n = n.strip()
                            if n: name_set.add(n)

            # Fallback 2: single-item inquiry_history
            if not name_set:
                cursor.execute("""
                    SELECT suppliers_found FROM inquiry_history
                    WHERE inquiry_id = %s LIMIT 1
                """, (inquiry_id,))
                h = cursor.fetchone()
                if h and h[0]:
                    for n in h[0].split(","):
                        n = n.strip()
                        if n: name_set.add(n)

            if name_set:
                name_list = [n.lower() for n in name_set]
                cursor.execute("""
                    SELECT vendor_name AS name, country, city, email, phone, website, brands, channel_codes
                    FROM vendors_master
                    WHERE LOWER(vendor_name) = ANY(%s::text[])
                    LIMIT 100
                """, (name_list,))
                master_cols = [d[0] for d in cursor.description]
                vendors = [dict(zip(master_cols, row)) for row in cursor.fetchall()]
                found_lower = {v["name"].lower() for v in vendors}

                # Also check legacy table for any not in vendors_master
                remaining = [n for n in name_list if n not in found_lower]
                if remaining:
                    cursor.execute("""
                        SELECT "Supplier Name" AS name, "Country" AS country, "City" AS city,
                               "Contact Email" AS email, "Phone" AS phone, "Website" AS website,
                               "Products / Brands Handled" AS brands,
                               "Supplier Type (Group A Channel)" AS channel_codes
                        FROM "Suppliers_Clean_Phase1"
                        WHERE LOWER("Supplier Name") = ANY(%s::text[])
                        LIMIT 100
                    """, (remaining,))
                    legacy_cols = [d[0] for d in cursor.description]
                    vendors += [dict(zip(legacy_cols, row)) for row in cursor.fetchall()]

        return {"success": True, "vendors": vendors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.get("/by-salesperson")
def get_by_salesperson(
    role: str = Query(...),
    division_ids: Optional[str] = Query(None),
    db=Depends(get_db)
):
    cursor = db.cursor()
    try:
        ids = [int(i) for i in division_ids.split(",")] if division_ids else []

        if role == "chairman" or not ids:
            cursor.execute("""
                SELECT
                    b.salesperson_name,
                    d.name  AS division_name,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE b.status='received') AS received,
                    COUNT(*) FILTER (WHERE b.status='lost')     AS lost,
                    COALESCE(SUM(b.quotation_value), 0)         AS total_value
                FROM bids_tracking b
                LEFT JOIN divisions d ON b.division_id = d.id
                GROUP BY b.salesperson_name, d.name
                ORDER BY total DESC
            """)
        else:
            ph = ",".join(["%s"] * len(ids))
            cursor.execute(f"""
                SELECT
                    b.salesperson_name,
                    d.name  AS division_name,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE b.status='received') AS received,
                    COUNT(*) FILTER (WHERE b.status='lost')     AS lost,
                    COALESCE(SUM(b.quotation_value), 0)         AS total_value
                FROM bids_tracking b
                LEFT JOIN divisions d ON b.division_id = d.id
                WHERE b.division_id IN ({ph})
                GROUP BY b.salesperson_name, d.name
                ORDER BY total DESC
            """, ids)

        columns = [desc[0] for desc in cursor.description]
        data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        for row in data:
            row['total_value'] = float(row['total_value'])

        return {"success": True, "data": data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


@router.delete("/{inquiry_id}")
def delete_rfq(inquiry_id: str, db=Depends(get_db)):
    cursor = db.cursor()
    try:
        # Delete line items first (FK), then master record
        cursor.execute("DELETE FROM inquiry_line_items WHERE inquiry_id = %s", (inquiry_id,))
        cursor.execute("DELETE FROM rfqs WHERE rfq_number = %s", (inquiry_id,))
        cursor.execute("DELETE FROM inquiry_master WHERE inquiry_id = %s", (inquiry_id,))
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()