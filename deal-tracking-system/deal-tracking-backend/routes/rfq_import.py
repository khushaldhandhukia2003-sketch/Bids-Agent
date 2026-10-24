import io
import os
import re
from datetime import datetime
from typing import List

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Depends, Header
from typing import Optional
from database import get_db, get_suppliers_db

router = APIRouter(prefix="/rfqs", tags=["RFQ Import"])

COLUMN_ALIASES = {
    "rfq_number": [
        "enquiry ref. no.", "enquiry ref no", "enquiry ref no.", "ref no", "rfq no",
        "rfq number", "rfq_number", "ref. no.", "ref no.", "enquiry_ref_no", "bid ref",
    ],
    "content": [
        "package description", "description", "package_description", "content",
        "item description", "item name", "scope of work", "scope",
    ],
    "submission_deadline": [
        "closing date", "deadline", "closing_date", "submission deadline",
        "submission_deadline", "due date", "bid closing date",
    ],
    "status": ["status", "bid status", "rfq status"],
    "client": ["client", "customer", "client name", "customer name", "end client"],
    "salesperson_name": [
        "salesperson", "sales person", "salesperson name",
        "sales person name", "salesperson_name", "account manager",
    ],
    "quotation_value": [
        "quotation value", "value", "quotation_value", "quote value",
        "amount", "bid value", "total value", "aed",
    ],
    "division_name": [
        "division", "division name", "division_name", "team", "department",
        "business unit", "bu",
    ],
}


def _normalize(col: str) -> str:
    return re.sub(r"\s+", " ", str(col).strip().lower())


def _map_columns(df_cols):
    norm = {_normalize(c): c for c in df_cols}
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in norm:
                mapping[field] = norm[alias]
                break
    return mapping


def _normalize_status(raw: str) -> str:
    raw = raw.strip().lower()
    if raw in ("received", "won", "awarded", "success"):
        return "received"
    if raw in ("lost", "no bid", "decline", "declined", "rejected"):
        return "lost"
    if raw in ("open", "pending", "in progress", "active"):
        return "open"
    return "open"


def _ensure_rfq_columns(cursor):
    """Add optional columns to rfqs if they don't exist yet."""
    extra_cols = [
        ("client",           "TEXT"),
        ("salesperson_name", "TEXT"),
        ("quotation_value",  "NUMERIC"),
        ("division_id",      "INTEGER REFERENCES divisions(id) ON DELETE SET NULL"),
    ]
    for col, col_type in extra_cols:
        try:
            cursor.execute(
                f"ALTER TABLE rfqs ADD COLUMN IF NOT EXISTS {col} {col_type}"
            )
        except Exception:
            pass


@router.post("/import")
async def import_rfqs(
    file: UploadFile = File(...),
    db=Depends(get_db),
    x_username:  Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
):
    try:
        contents = await file.read()
        fname = (file.filename or "").lower()

        if fname.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents), dtype=str)
        else:
            # Try header at row 0 first; if too few recognisable columns, retry at row 9
            df = pd.read_excel(io.BytesIO(contents), header=0, dtype=str)
            col_map_attempt = _map_columns(df.columns)
            if "rfq_number" not in col_map_attempt:
                df = pd.read_excel(io.BytesIO(contents), header=9, dtype=str)

        df = df.dropna(how="all")
        df.columns = [str(c).strip() for c in df.columns]

        col_map = _map_columns(df.columns)

        if "rfq_number" not in col_map:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not find a Reference Number column. "
                    "Expected headers like 'Enquiry Ref. No.', 'RFQ No', 'Ref No'."
                ),
            )

        cursor = db.cursor()

        # Ensure optional columns and unique constraint exist
        _ensure_rfq_columns(cursor)
        cursor.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE tablename='rfqs' AND indexname='rfqs_rfq_number_key'
                ) THEN
                    ALTER TABLE rfqs ADD CONSTRAINT rfqs_rfq_number_key UNIQUE (rfq_number);
                END IF;
            END $$;
        """)
        db.commit()

        # Load division name/code → id map
        cursor.execute("SELECT id, name, code FROM divisions")
        div_map: dict[str, int] = {}
        for did, dname, dcode in cursor.fetchall():
            div_map[dname.strip().lower()] = did
            div_map[dcode.strip().lower()] = did

        inserted = updated = skipped = 0
        errors: list[str] = []

        for idx, row in df.iterrows():
            try:
                ref_no = str(row.get(col_map["rfq_number"], "")).strip()
                if not ref_no or ref_no.lower() in ("nan", "none", ""):
                    skipped += 1
                    continue

                content = (
                    str(row[col_map["content"]]).strip()
                    if "content" in col_map else None
                )

                # Closing date
                deadline = None
                if "submission_deadline" in col_map:
                    raw_d = row.get(col_map["submission_deadline"], "")
                    if raw_d and str(raw_d).lower() not in ("nan", "none", ""):
                        try:
                            deadline = pd.to_datetime(
                                raw_d, dayfirst=True, errors="coerce"
                            )
                            deadline = None if pd.isna(deadline) else deadline.date()
                        except Exception:
                            deadline = None

                status_raw = (
                    str(row[col_map["status"]]).strip()
                    if "status" in col_map else "open"
                )
                status = _normalize_status(
                    status_raw if status_raw.lower() not in ("nan", "none", "") else "open"
                )

                # Quotation value
                q_value = None
                if "quotation_value" in col_map:
                    raw_v = row.get(col_map["quotation_value"], "")
                    if raw_v and str(raw_v).lower() not in ("nan", "none", ""):
                        try:
                            q_value = float(
                                str(raw_v).replace(",", "").replace("$", "").strip()
                            )
                        except Exception:
                            pass

                # Division
                division_id = None
                if "division_name" in col_map:
                    raw_div = str(row.get(col_map["division_name"], "")).strip().lower()
                    division_id = div_map.get(raw_div)

                # Client / salesperson (stored in rfqs if columns exist, else skip gracefully)
                client = (
                    str(row[col_map["client"]]).strip()
                    if "client" in col_map else None
                )
                salesperson = (
                    str(row[col_map["salesperson_name"]]).strip()
                    if "salesperson_name" in col_map else None
                )
                if client and client.lower() in ("nan", "none"):
                    client = None
                if salesperson and salesperson.lower() in ("nan", "none"):
                    salesperson = None

                # Upsert into rfqs — use rfq_number as conflict key
                cursor.execute(
                    """
                    INSERT INTO rfqs
                        (rfq_number, content, submission_deadline, status, division_id,
                         client, salesperson_name, quotation_value)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (rfq_number) DO UPDATE SET
                        content            = COALESCE(EXCLUDED.content,            rfqs.content),
                        submission_deadline= COALESCE(EXCLUDED.submission_deadline, rfqs.submission_deadline),
                        status             = EXCLUDED.status,
                        division_id        = COALESCE(EXCLUDED.division_id,        rfqs.division_id),
                        client             = COALESCE(EXCLUDED.client,             rfqs.client),
                        salesperson_name   = COALESCE(EXCLUDED.salesperson_name,   rfqs.salesperson_name),
                        quotation_value    = COALESCE(EXCLUDED.quotation_value,    rfqs.quotation_value)
                    RETURNING id, xmax
                    """,
                    (ref_no, content, deadline, status, division_id,
                     client, salesperson, q_value),
                )
                result = cursor.fetchone()
                rfq_id, xmax = result
                if xmax == 0:
                    inserted += 1
                else:
                    updated += 1

                # Insert a basic rfq_item (ignore if one already exists for this rfq)
                cursor.execute(
                    """
                    INSERT INTO rfq_items (rfq_id, item_name, description)
                    SELECT %s, %s, %s
                    WHERE NOT EXISTS (SELECT 1 FROM rfq_items WHERE rfq_id = %s)
                    """,
                    (rfq_id, content or ref_no, client or "", rfq_id),
                )

                # Also upsert into inquiry_master so this RFQ appears in the RFQ tab
                cursor.execute(
                    """
                    INSERT INTO inquiry_master
                        (inquiry_id, client, delivery, notes, total_items, division_id, closing_date, is_draft)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
                    ON CONFLICT (inquiry_id) DO UPDATE SET
                        client      = COALESCE(EXCLUDED.client,      inquiry_master.client),
                        division_id = COALESCE(EXCLUDED.division_id, inquiry_master.division_id),
                        closing_date= COALESCE(EXCLUDED.closing_date,inquiry_master.closing_date),
                        is_draft    = FALSE
                    """,
                    (ref_no, client, None, content, 0, division_id, deadline),
                )

            except Exception as exc:
                errors.append(f"Row {idx + 2}: {exc}")
                skipped += 1
                db.rollback()
                continue

        db.commit()
        cursor.close()

        # Log to activity feed
        try:
            from routes.history import log_activity
            log_activity(
                event_type="rfq_import",
                title=f"RFQ Import — {file.filename}",
                detail=f"{inserted} new, {updated} updated, {skipped} skipped",
                meta={"filename": file.filename, "inserted": inserted, "updated": updated, "skipped": skipped},
                username=x_username,
                user_role=x_user_role,
            )
        except Exception:
            pass

        return {
            "success": True,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "total_processed": inserted + updated,
            "columns_detected": list(col_map.keys()),
            "errors": errors[:10],
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── MTO / Ariba RFQ → inquiry_master + inquiry_line_items ─────────────────

MTO_ALIASES = {
    "description": ["type", "item description", "description", "name", "item name", "material description"],
    "part_number":  ["tag no.", "tag no", "tag number", "item no", "item no.", "number", "sl no.", "sl no"],
    "quantity":     ["qty", "quantity", "q'ty", "nos", "no.", "count"],
    "unit":         ["unit", "uom", "unit of measure"],
    "specs":        [
        "sp item size (inch)", "sp item size", "header size (inch)", "header size",
        "size", "rating", "sp item material pipe class", "pipe class",
        "description", "technical specification",
    ],
}


def _normalize_mto(col: str) -> str:
    return re.sub(r"\s+", " ", str(col).strip().lower())


def _map_mto_columns(df_cols):
    norm = {_normalize_mto(c): c for c in df_cols}
    mapping = {}
    for field, aliases in MTO_ALIASES.items():
        for alias in aliases:
            if alias in norm and field not in mapping:
                mapping[field] = norm[alias]
    return mapping


def _detect_best_df(contents: bytes, fname: str) -> pd.DataFrame:
    """
    Try every sheet × header rows 0,1,8,9,10.
    Return the dataframe with the most recognised MTO columns.
    Falls back to the largest sheet if nothing scores.
    """
    engine = "xlrd" if fname.endswith(".xls") else None
    best_df, best_score, biggest_df, biggest_rows = None, -1, None, -1

    # Get sheet names
    try:
        xl = pd.ExcelFile(io.BytesIO(contents), engine=engine)
        sheet_names = xl.sheet_names
    except Exception:
        sheet_names = [0]

    for sheet in sheet_names:
        for hdr in [0, 1, 8, 9, 10]:
            try:
                kwargs = {"header": hdr, "dtype": str, "sheet_name": sheet}
                if engine:
                    kwargs["engine"] = engine
                df = pd.read_excel(io.BytesIO(contents), **kwargs)
                df = df.dropna(how="all")
                if df.empty:
                    continue
                score = len(_map_mto_columns(df.columns))
                if score > best_score:
                    best_score, best_df = score, df
                if len(df) > biggest_rows:
                    biggest_rows, biggest_df = len(df), df
            except Exception:
                continue

    return best_df if best_df is not None else biggest_df


def _llm_map_columns(df: pd.DataFrame) -> dict:
    """
    Ask the LLM to identify which columns contain description, quantity, unit, part_number, specs.
    Returns a mapping like {"description": "Name", "quantity": "Quantity", ...}
    """
    try:
        from services.openai_fallback import parse_with_llm
        cols = list(df.columns[:30])  # cap at 30 cols
        sample = df.head(3).to_dict(orient="records")
        prompt = f"""You are parsing an Excel RFQ/procurement file.
Column headers: {cols}
Sample rows (first 3): {sample}

Return a JSON object mapping these field names to the exact column header that best matches each:
- "description": the column containing item name, type, or description
- "quantity": the column containing quantity or count
- "unit": the column containing unit of measure (each, pcs, m, kg, etc.)
- "part_number": the column containing part number, tag, item number, or reference
- "specs": the column containing technical specs, size, rating, or material

Only include fields where you are confident. Use the exact column header string.
Return only valid JSON, no explanation.
Example: {{"description": "Name", "quantity": "Quantity", "unit": "Unit of Measure"}}"""

        raw = parse_with_llm(prompt, max_tokens=300)
        import json as _json
        result = _json.loads(raw.strip().strip("```json").strip("```").strip())
        # Validate that returned column names actually exist
        valid = {k: v for k, v in result.items() if v in df.columns}
        print(f"  LLM column mapping: {valid}")
        return valid
    except Exception as e:
        print(f"  LLM column mapping failed: {e}")
        return {}


def _stem(filename: str) -> str:
    """Return filename without extension, used as inquiry_id."""
    return os.path.splitext(filename)[0].strip()


def _parse_rfq_direct(text: str, source_name: str = "rfq") -> tuple:
    """
    Single AI call that extracts client/delivery + all items at once.
    Returns (parsed_dict, items_list) — replaces 2 separate AI calls.
    """
    import json, re as _re
    from services.openai_fallback import parse_with_llm

    prompt = f"""You are parsing a procurement RFQ / item list document.
Extract all information and return ONLY a valid JSON object with this exact structure:

{{
  "client": "client/customer name or null",
  "delivery": "delivery location or null",
  "items": [
    {{
      "description": "full item description",
      "part_number": "part/tag/reference number or empty string",
      "quantity": "numeric quantity or empty string",
      "unit": "unit of measure (each, pcs, m, kg, set, etc.) or empty string",
      "specs": "technical specifications, size, rating, material or empty string",
      "category": "product category (e.g. Valves, Pumps, Instrumentation, etc.)"
    }}
  ]
}}

Rules:
- Include EVERY line item — do not skip or summarize
- If a field is unknown leave it as empty string, not null
- Return ONLY the JSON, no markdown, no explanation

Document:
{text[:12000]}"""

    def _parse_result(raw):
        raw = _re.sub(r"```json|```", "", raw).strip()
        result = json.loads(raw)
        parsed = {"client": result.get("client"), "delivery": result.get("delivery")}
        items  = result.get("items", [])
        return parsed, items if items else None

    # Try Groq first (free, ~2s) — fast enough for most RFQs
    try:
        from services.groq_client import ask_groq
        raw = ask_groq(prompt, json_mode=True, max_tokens=2000)
        parsed, items = _parse_result(raw)
        if items:
            print(f"  Groq direct parse: {len(items)} items")
            return parsed, items
    except Exception as e:
        print(f"  Groq parse failed: {e} — falling back to Claude/GPT")

    try:
        raw = parse_with_llm(prompt, max_tokens=2000)
        raw = _re.sub(r"```json|```", "", raw).strip()
        result = json.loads(raw)
        parsed = {"client": result.get("client"), "delivery": result.get("delivery")}
        items  = result.get("items", [])
        return parsed, items
    except Exception as e:
        print(f"  Direct parse failed ({e}), falling back to pipeline")
        return None, None


def _parse_pdf_direct(contents: bytes, fname: str) -> tuple:
    """
    Send PDF bytes directly to Claude in ONE API call — extract + parse together.
    Fastest path for PDFs. Returns (parsed_dict, items_list).
    """
    import base64, json, re as _re, os

    pdf_b64 = base64.standard_b64encode(contents).decode("utf-8")
    prompt_text = """You are parsing a procurement RFQ / item list PDF.
Extract all information and return ONLY a valid JSON object with this exact structure:

{
  "client": "client/customer name or null",
  "delivery": "delivery location or null",
  "items": [
    {
      "description": "full item description",
      "part_number": "part/tag/reference number or empty string",
      "quantity": "numeric quantity or empty string",
      "unit": "unit of measure (each, pcs, m, kg, set, etc.) or empty string",
      "specs": "technical specifications, size, rating, material or empty string",
      "category": "product category (e.g. Valves, Pumps, Instrumentation, etc.)"
    }
  ]
}

Rules:
- Include EVERY line item — do not skip or summarize
- If a field is unknown leave it as empty string
- Return ONLY the JSON, no markdown, no explanation"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
                    {"type": "text", "text": prompt_text}
                ]
            }]
        )
        raw = _re.sub(r"```json|```", "", response.content[0].text).strip()
        result = json.loads(raw)
        parsed = {"client": result.get("client"), "delivery": result.get("delivery")}
        items  = result.get("items", [])
        print(f"  Claude PDF direct parse: {len(items)} items")
        return parsed, items
    except Exception as e:
        print(f"  PDF direct parse failed: {e}")
        return None, None


async def _save_rfq_to_db(db, inquiry_id: str, fname: str, parsed: dict, items: list):
    """Save parsed RFQ to inquiry_master + inquiry_line_items + rfqs."""
    cur = db.cursor()

    if items:
        descs = [it["description"] for it in items if it.get("description")][:3]
        description = ", ".join(descs) + (f" … (+{len(items)-3} more)" if len(items) > 3 else "")
    else:
        description = fname

    cur.execute("""
        INSERT INTO inquiry_master (inquiry_id, client, delivery, notes, total_items, is_draft)
        VALUES (%s, %s, %s, %s, %s, FALSE)
        ON CONFLICT (inquiry_id) DO UPDATE SET
            client      = COALESCE(EXCLUDED.client,   inquiry_master.client),
            delivery    = COALESCE(EXCLUDED.delivery, inquiry_master.delivery),
            notes       = EXCLUDED.notes,
            total_items = EXCLUDED.total_items,
            is_draft    = FALSE
    """, (inquiry_id, parsed.get("client"), parsed.get("delivery"), description, len(items)))
    db.commit()

    cur.execute("DELETE FROM inquiry_line_items WHERE inquiry_id = %s", (inquiry_id,))
    inserted = 0
    for i, item in enumerate(items):
        desc = (item.get("description") or "").strip()
        if not desc:
            continue
        cur.execute("""
            INSERT INTO inquiry_line_items
                (inquiry_id, line_ref, description, quantity, unit, specs, category)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (inquiry_id, item.get("part_number") or str(i+1), desc,
              item.get("quantity",""), item.get("unit",""),
              item.get("specs",""), item.get("category","")))
        inserted += 1

    try:
        cur.execute("""
            INSERT INTO rfqs (rfq_number, content, status)
            VALUES (%s, %s, 'open')
            ON CONFLICT (rfq_number) DO NOTHING
        """, (inquiry_id, parsed.get("client") or fname))
    except Exception:
        pass

    db.commit()
    cur.close()
    return inserted


@router.post("/import-rfq-text")
async def import_rfq_text(
    text: str = Form(...),
    inquiry_id: str = Form(...),
    db=Depends(get_suppliers_db)
):
    """Import RFQ from pasted text — single AI call, very fast."""
    try:
        parsed, items = _parse_rfq_direct(text, inquiry_id)
        if not items:
            from services.inquiry_parser import parse_inquiry_document, group_items_by_category
            p = parse_inquiry_document(text)
            groups = group_items_by_category(p)
            parsed = p
            items = [{"description": it.get("description",""), "part_number": it.get("part_number",""),
                      "quantity": str(it.get("quantity","")), "unit": it.get("unit",""),
                      "specs": it.get("specs",""), "category": g.get("category_name","")}
                     for g in groups for it in g.get("items",[])]

        inserted = await _save_rfq_to_db(db, inquiry_id, inquiry_id, parsed or {}, items)
        return {"success": True, "inquiry_id": inquiry_id, "inserted": inserted,
                "items": items, "client": (parsed or {}).get("client"),
                "delivery": (parsed or {}).get("delivery")}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/import-rfq-excel")
async def import_rfq_excel(file: UploadFile = File(...), db=Depends(get_suppliers_db)):
    """
    Parse any RFQ file. PDFs go through a single Claude call (fast).
    Other formats use text extraction then a combined parse call.
    """
    import tempfile
    from services.inquiry_parser import parse_inquiry_document, group_items_by_category

    try:
        fname      = file.filename or "rfq"
        inquiry_id = _stem(fname)
        contents   = await file.read()
        suffix     = os.path.splitext(fname)[1].lower()

        parsed, items = None, None

        # ── PDFs: one Claude API call (extract + parse together) ──
        if suffix == ".pdf":
            print(f"  PDF fast path: {fname} ({len(contents)//1024} KB)")
            parsed, items = _parse_pdf_direct(contents, fname)

        # ── All other formats: extract text → single combined parse ──
        if items is None:
            from services.documentParser import extract_text
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(contents)
                tmp_path = tmp.name
            try:
                text = extract_text(tmp_path)
            finally:
                try: os.remove(tmp_path)
                except: pass

            if not text or not text.strip():
                raise HTTPException(status_code=400, detail="Could not extract text from file.")

            print(f"  import-rfq | {fname} | {len(text)} chars — combined parse")
            parsed, items = _parse_rfq_direct(text, fname)

            # Final fallback to old pipeline if combined parse fails
            if items is None:
                p = parse_inquiry_document(text)
                groups = group_items_by_category(p)
                parsed = p
                items = [{"description": it.get("description",""), "part_number": it.get("part_number",""),
                          "quantity": str(it.get("quantity","")), "unit": it.get("unit",""),
                          "specs": it.get("specs",""), "category": g.get("category_name","")}
                         for g in groups for it in g.get("items",[])]

        inserted = await _save_rfq_to_db(db, inquiry_id, fname, parsed or {}, items or [])

        return {
            "success":    True,
            "inquiry_id": inquiry_id,
            "inserted":   inserted,
            "skipped":    0,
            "errors":     [],
            "items":      items or [],
            "client":     (parsed or {}).get("client"),
            "delivery":   (parsed or {}).get("delivery"),
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/import-rfq-excel-multi")
async def import_rfq_excel_multi(files: List[UploadFile] = File(...), db=Depends(get_suppliers_db)):
    """
    Parse multiple RFQ files and merge them into ONE single RFQ record.
    All items from all files are combined. inquiry_id is taken from the first file's stem.
    """
    import tempfile
    from services.documentParser import extract_text
    from services.inquiry_parser import parse_inquiry_document, group_items_by_category

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    combined_parts = []
    first_fname = None

    for file in files:
        fname = file.filename or "rfq"
        if first_fname is None:
            first_fname = fname
        contents = await file.read()
        suffix = os.path.splitext(fname)[1].lower()

        text = None
        # PDFs: direct parse
        if suffix == ".pdf":
            try:
                parsed_pdf, items_pdf = _parse_pdf_direct(contents, fname)
                if items_pdf:
                    # Convert parsed items back to text for merging
                    item_lines = "\n".join(
                        f"- {it.get('description','')} qty:{it.get('quantity','')} unit:{it.get('unit','')}"
                        for it in items_pdf if it.get("description")
                    )
                    client_line = f"Client: {parsed_pdf.get('client','')}" if parsed_pdf and parsed_pdf.get('client') else ""
                    text = f"{client_line}\n{item_lines}".strip()
            except Exception:
                pass

        if not text:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(contents)
                tmp_path = tmp.name
            try:
                text = extract_text(tmp_path)
            finally:
                try: os.remove(tmp_path)
                except: pass

        if text and text.strip():
            combined_parts.append(f"--- Document: {fname} ---\n{text.strip()}")

    if not combined_parts:
        raise HTTPException(status_code=400, detail="Could not extract text from any of the uploaded files.")

    combined_text = "\n\n".join(combined_parts)
    inquiry_id = _stem(first_fname)

    # Parse all combined text as ONE inquiry
    parsed, items = _parse_rfq_direct(combined_text, first_fname)
    if items is None:
        p = parse_inquiry_document(combined_text)
        groups = group_items_by_category(p)
        parsed = p
        items = [
            {"description": it.get("description",""), "part_number": it.get("reference") or it.get("part_number",""),
             "quantity": str(it.get("quantity","")), "unit": it.get("unit",""),
             "specs": it.get("specs",""), "category": g.get("category_name","")}
            for g in groups for it in g.get("items",[])
        ]

    inserted = await _save_rfq_to_db(db, inquiry_id, first_fname, parsed or {}, items or [])

    return {
        "success":    True,
        "inquiry_id": inquiry_id,
        "inserted":   inserted,
        "skipped":    0,
        "errors":     [],
        "items":      items or [],
        "client":     (parsed or {}).get("client"),
        "delivery":   (parsed or {}).get("delivery"),
        "files_merged": len(combined_parts),
    }


@router.post("/import-vendors-for-rfq")
async def import_vendors_for_rfq(
    file: UploadFile = File(...),
    inquiry_id: str = Form(None),
    db=Depends(get_suppliers_db)
):
    """
    Import vendor list Excel and link to an inquiry.
    Uses the explicitly provided inquiry_id; falls back to the filename stem.
    """
    try:
        contents = await file.read()
        fname = file.filename or "vendors"
        inquiry_id = (inquiry_id or "").strip() or _stem(fname)

        df = _detect_best_df(contents, fname.lower())
        if df is None:
            raise HTTPException(status_code=400, detail="Could not read vendor file as Excel.")

        df.columns = [str(c).strip() for c in df.columns]
        df = df.dropna(how="all")

        VENDOR_ALIASES = {
            "vendor_name": ["vendor name", "supplier name", "company", "company name", "name", "supplier"],
            "email":       ["email", "e-mail", "email address", "contact email", "official email",
                            "official e-mail", "official email address", "email id", "mail", "email / website"],
            "phone":       ["phone", "telephone", "tel", "mobile", "contact no", "contact number",
                            "official phone number", "official phone", "phone number", "phone no",
                            "phone no.", "contact", "ph", "fax/phone"],
            "website":     ["website", "web", "url", "www", "web address", "website url"],
            "country":     ["country", "location", "region", "country / region"],
            "city":        ["city", "state", "city / state"],
            "brands":      ["brands", "brand", "make", "makes", "products", "product"],
        }

        norm = {_normalize_mto(c): c for c in df.columns}
        vcol = {}
        for field, aliases in VENDOR_ALIASES.items():
            for alias in aliases:
                if alias in norm and field not in vcol:
                    vcol[field] = norm[alias]

        if "vendor_name" not in vcol:
            raise HTTPException(status_code=400, detail="Could not find vendor name column.")

        cur = db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS discovered_vendors (
                id                 SERIAL PRIMARY KEY,
                vendor_name        TEXT,
                country            TEXT,
                city               TEXT,
                email              TEXT,
                phone              TEXT,
                website            TEXT,
                brands             TEXT,
                description        TEXT,
                sourcing_rationale TEXT,
                source             TEXT,
                search_id          TEXT,
                inquiry_id         TEXT,
                created_at         TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        from routes.vendor_management import upsert_to_master

        # Replace any existing vendors for this inquiry with the uploaded Excel list
        cur.execute("DELETE FROM discovered_vendors WHERE inquiry_id = %s", (inquiry_id,))

        inserted = 0
        skipped = 0

        for _, row in df.iterrows():
            name = str(row.get(vcol["vendor_name"], "")).strip()
            if not name or name.lower() in ("nan", "none", ""):
                skipped += 1
                continue

            def g(field):
                if field not in vcol:
                    return None
                v = str(row.get(vcol[field], "")).strip()
                return None if v.lower() in ("nan", "none", "") else v

            email   = g("email")
            phone   = g("phone")
            website = g("website")
            country = g("country")
            city    = g("city")
            brands  = g("brands")

            # Save to discovered_vendors (linked to inquiry)
            cur.execute("""
                INSERT INTO discovered_vendors
                    (vendor_name, email, phone, website, country, city, brands, source, inquiry_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, email, phone, website, country, city, brands, "imported", inquiry_id))

            # Also save to vendors_master so it appears in Vendor Directory
            try:
                upsert_to_master({
                    "vendor_name":            name,
                    "email":                  email,
                    "phone":                  phone,
                    "website":                website,
                    "country":                country,
                    "city":                   city,
                    "brands":                 brands,
                    "source":                 "imported",
                    "verification_method":    "imported",
                    "verification_confidence": 0.6,
                }, db)
            except Exception as e:
                print(f"  vendors_master upsert failed for {name}: {e}")

            inserted += 1

        # Log to vendor_import_log so it appears in History
        try:
            cur.execute("""
                INSERT INTO vendor_import_log (filename, saved, updated, skipped, total_rows)
                VALUES (%s, %s, %s, %s, %s)
            """, (fname, inserted, 0, skipped, inserted + skipped))
        except Exception:
            pass

        db.commit()
        cur.close()

        # Return first 50 vendors for preview
        cur2 = db.cursor()
        cur2.execute("""
            SELECT vendor_name AS name, country, city, email, phone, website, brands
            FROM discovered_vendors WHERE inquiry_id = %s ORDER BY id DESC LIMIT 50
        """, (inquiry_id,))
        cols = [d[0] for d in cur2.description]
        vendors_preview = [dict(zip(cols, r)) for r in cur2.fetchall()]
        cur2.close()

        return {
            "success":    True,
            "inquiry_id": inquiry_id,
            "inserted":   inserted,
            "skipped":    skipped,
            "vendors":    vendors_preview,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
