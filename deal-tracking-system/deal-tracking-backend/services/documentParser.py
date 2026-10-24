"""
services/documentParser.py

Extracts text from uploaded files for inquiry parsing.

Supported formats:
  Documents : PDF, DOCX, DOC, TXT, CSV
  Images    : PNG, JPG, JPEG, WEBP, BMP, GIF  (via Groq vision)
  Excel     : XLS, XLSX, XLSM                 (multi-sheet, auto-detects inquiry sheet)

Excel strategy:
  1. Read every sheet into a text preview (first 50 rows each)
  2. Send all sheet previews to Groq — ask it which sheet contains the inquiry/item list
  3. Extract only that sheet as pipe-separated text
  4. Pass to parse_inquiry_document() as normal
"""

import os
import re
import base64
from typing import Optional


# ── Text-based formats ────────────────────────────────────────

def extract_from_pdf(file_path: str) -> str:
    """
    Extract text from PDF.
    1. pdfplumber / pdfminer  — fast, for text-based PDFs
    2. Claude PDF document API — single call handles any PDF (text or scanned)
    """
    text = ""

    # ── Attempt 1: pdfplumber ─────────────────────────────────
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        text = text.strip()
        if text and len(text) >= 100:
            print(f"  pdfplumber extracted {len(text)} chars")
            return text
    except Exception as e:
        print(f"  pdfplumber failed: {e}")

    # ── Attempt 2: pdfminer (better for complex layouts) ──────
    if not text or len(text) < 100:
        try:
            from pdfminer.high_level import extract_text as pdfminer_extract
            text = (pdfminer_extract(file_path) or "").strip()
            if text and len(text) >= 100:
                print(f"  pdfminer extracted {len(text)} chars")
                return text
        except Exception as e:
            print(f"  pdfminer failed: {e}")

    # ── Attempt 3: Claude PDF document API (scanned or complex) ─
    print("  Text extraction insufficient — sending PDF directly to Claude")
    try:
        text = _extract_pdf_via_claude(file_path)
        if text:
            print(f"  Claude PDF extracted {len(text)} chars")
            return text
    except Exception as e:
        print(f"  Claude PDF extraction failed: {e}")

    if not text:
        raise Exception("Could not extract text from PDF.")

    return text


def _extract_pdf_via_claude(file_path: str) -> str:
    """
    Send the PDF directly to Claude as a document — works for both
    text-based and scanned PDFs in a single API call.
    """
    import base64
    import os

    with open(file_path, "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    file_size_kb = os.path.getsize(file_path) / 1024
    print(f"  Sending {file_size_kb:.0f} KB PDF to Claude")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract ALL text from this document exactly as it appears. "
                            "Preserve tables using pipe (|) separators for columns. "
                            "Include every item description, part number, quantity, unit, "
                            "specification, and reference visible. Do not summarize."
                        )
                    }
                ]
            }]
        )
        return response.content[0].text.strip()
    except Exception as e:
        # fallback to openai vision if anthropic fails
        print(f"  Claude PDF API failed ({e}) — trying OpenAI vision")
        return _extract_pdf_via_vision(file_path)


def _extract_pdf_via_vision(file_path: str) -> str:
    """
    Convert PDF pages to images and run vision AI on each page.
    Works for scanned PDFs / image-only PDFs.
    """
    from services.openai_fallback import parse_with_llm_vision

    pages_text = []

    # ── Strategy A: pdf2image (requires poppler) ──────────────
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(file_path, dpi=150, first_page=1, last_page=8)
        print(f"  pdf2image: converted {len(images)} page(s)")
        for i, img in enumerate(images):
            import io, base64
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.standard_b64encode(buf.getvalue()).decode()
            data_url = f"data:image/png;base64,{b64}"
            page_text = parse_with_llm_vision(data_url, _IMAGE_PROMPT, max_tokens=3000)
            if page_text:
                pages_text.append(f"--- Page {i+1} ---\n{page_text}")
        if pages_text:
            return "\n\n".join(pages_text)
    except ImportError:
        print("  pdf2image not installed — trying pymupdf")
    except Exception as e:
        print(f"  pdf2image failed: {e} — trying pymupdf")

    # ── Strategy B: pymupdf (fitz) ────────────────────────────
    try:
        import fitz  # PyMuPDF
        import io, base64
        doc = fitz.open(file_path)
        for i, page in enumerate(doc):
            if i >= 8:  # cap at 8 pages
                break
            pix = page.get_pixmap(dpi=150)
            buf = io.BytesIO(pix.tobytes("png"))
            b64 = base64.standard_b64encode(buf.getvalue()).decode()
            data_url = f"data:image/png;base64,{b64}"
            page_text = parse_with_llm_vision(data_url, _IMAGE_PROMPT, max_tokens=3000)
            if page_text:
                pages_text.append(f"--- Page {i+1} ---\n{page_text}")
        doc.close()
        if pages_text:
            return "\n\n".join(pages_text)
    except ImportError:
        print("  pymupdf not installed")
    except Exception as e:
        print(f"  pymupdf failed: {e}")

    return ""


def extract_from_docx(file_path: str) -> str:
    try:
        from docx import Document
        doc  = Document(file_path)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text.strip()
    except Exception as e:
        raise Exception(f"DOCX extraction failed: {e}")


# ── Excel format ──────────────────────────────────────────────

def extract_from_excel(file_path: str) -> str:
    """
    Reads an Excel file with any number of sheets.
    Uses Groq to identify which sheet contains the procurement inquiry,
    then extracts and returns that sheet as structured text.
    """
    try:
        import pandas as pd
    except ImportError:
        raise Exception("pandas is required for Excel parsing. Run: pip install pandas openpyxl xlrd")

    print(f"  Reading Excel file: {os.path.basename(file_path)}")

    # ── Step 1: Read all sheets ───────────────────────────────
    try:
        ext = os.path.splitext(file_path)[1].lower()
        engine = "xlrd" if ext == ".xls" else "openpyxl"
        try:
            all_sheets = pd.read_excel(file_path, sheet_name=None, header=None, engine=engine)
        except Exception as inner:
            # Fallback: file may be HTML exported with .xls extension (common from ERP/web systems)
            err_str = str(inner).lower()
            if "bof" in err_str or "style" in err_str or "html" in err_str or "unsupported format" in err_str:
                try:
                    html_sheets = pd.read_html(file_path)
                    all_sheets = {f"Sheet{i+1}": df for i, df in enumerate(html_sheets)}
                except Exception:
                    raise Exception(f"Could not open Excel file: {inner}")
            else:
                raise Exception(f"Could not open Excel file: {inner}")
    except Exception as e:
        raise Exception(f"Could not open Excel file: {e}")

    sheet_names = list(all_sheets.keys())
    print(f"  Found {len(sheet_names)} sheet(s): {sheet_names}")

    # If only one sheet, skip the identification step
    if len(sheet_names) == 1:
        print(f"  Single sheet — using: {sheet_names[0]}")
        return _sheet_to_text(all_sheets[sheet_names[0]], sheet_names[0])

    # ── Step 2: Build preview of each sheet ──────────────────
    # Send first 30 rows of each sheet to Groq for identification
    # Keep it compact — we just need enough for Groq to judge
    sheet_previews = {}
    for name, df in all_sheets.items():
        # Drop completely empty rows/cols
        df_clean = df.dropna(how="all").dropna(axis=1, how="all")
        if df_clean.empty:
            sheet_previews[name] = "(empty sheet)"
            continue
        # Take first 30 rows, convert to readable text
        preview_rows = df_clean.head(30).fillna("").astype(str)
        lines = []
        for _, row in preview_rows.iterrows():
            row_text = " | ".join(v.strip() for v in row.values if v.strip())
            if row_text:
                lines.append(row_text)
        sheet_previews[name] = "\n".join(lines[:30]) if lines else "(no readable content)"

    # ── Step 3: Identify inquiry sheet ───────────────────────
    # Fast heuristic first — skip LLM if sheet name is obvious
    INQUIRY_KEYWORDS = ["boq", "item", "material", "product", "inquiry", "enquiry",
                        "quotation", "rfq", "pr ", "purchase", "bom", "scope"]
    SKIP_KEYWORDS    = ["instruction", "respond", "submit", "cover", "terms",
                        "evaluation", "criteria", "currency", "guide"]
    heuristic_match = None
    for name in sheet_previews:
        nl = name.lower()
        if any(kw in nl for kw in INQUIRY_KEYWORDS) and not any(kw in nl for kw in SKIP_KEYWORDS):
            heuristic_match = name
            break
    if heuristic_match:
        inquiry_sheet_name = heuristic_match
        print(f"  Heuristic identified inquiry sheet: '{inquiry_sheet_name}'")
    else:
        inquiry_sheet_name = _identify_inquiry_sheet(sheet_previews)
    print(f"  Using sheet: '{inquiry_sheet_name}'")

    # ── Step 4: Extract that sheet as text ────────────────────
    if inquiry_sheet_name not in all_sheets:
        # Fallback — use the sheet with the most non-empty rows
        print(f"  Warning: identified sheet not found, using largest sheet")
        inquiry_sheet_name = max(
            all_sheets.keys(),
            key=lambda n: all_sheets[n].dropna(how="all").shape[0]
        )

    return _sheet_to_text(all_sheets[inquiry_sheet_name], inquiry_sheet_name)


def _identify_inquiry_sheet(sheet_previews: dict) -> str:
    """
    Identifies which sheet contains the procurement inquiry.
    Uses Claude → GPT-4o-mini, then heuristic fallback.
    """
    from services.openai_fallback import parse_with_llm
    import json

    sheets_text = ""
    for name, preview in sheet_previews.items():
        sheets_text += f"\n--- Sheet: {name} ---\n{preview}\n"

    prompt = f"""You are reviewing an Excel file with multiple sheets.
Identify which sheet contains the actual procurement item list or Bill of Quantities (BOQ)
— the sheet listing products, materials, or equipment being requested for purchase with quantities.

Ignore sheets that contain:
- Instructions or guidelines (e.g. "Intend To Respond Instructions")
- Currency conversion tables
- Terms and conditions
- Technical or commercial evaluation criteria
- Cover pages or project descriptions

The correct sheet typically contains:
- Item descriptions or part numbers
- Quantities and units
- Columns like: Item No, Description, Qty, Unit, Part Number

Here are previews of all sheets:
{sheets_text}

Return ONLY a JSON object:
{{"inquiry_sheet": "exact sheet name here"}}"""

    # Try Groq first (free, ~1s) then Claude fallback
    def _try_parse(raw):
        result = json.loads(re.sub(r"```json|```", "", raw).strip())
        sheet  = result.get("inquiry_sheet", "")
        return sheet if sheet and sheet in sheet_previews else None

    try:
        from services.groq_client import ask_groq
        raw   = ask_groq(prompt, json_mode=True, max_tokens=100)
        sheet = _try_parse(raw)
        if sheet:
            print(f"  Groq identified inquiry sheet: '{sheet}'")
            return sheet
    except Exception:
        pass

    try:
        raw    = parse_with_llm(prompt, max_tokens=200)
        sheet  = _try_parse(raw)
        if sheet:
            print(f"  LLM identified inquiry sheet: '{sheet}'")
            return sheet
    except Exception as e:
        print(f"  Sheet identification failed: {e} — using heuristic")

    # Final heuristic fallback — pick sheet with most rows and numeric content
    # Exclude sheets with instruction-like names
    skip_keywords = ["instruction", "respond", "submit", "cover", "terms", "evaluation"]
    candidates = {
        name: preview for name, preview in sheet_previews.items()
        if not any(kw in name.lower() for kw in skip_keywords)
        and preview != "(empty sheet)"
    }
    if candidates:
        best = max(candidates, key=lambda n: len(candidates[n]))
        print(f"  Heuristic selected sheet: '{best}'")
        return best

    # Absolute last resort
    return list(sheet_previews.keys())[0]


def _sheet_to_text(df, sheet_name: str) -> str:
    """
    Converts a DataFrame (one Excel sheet) to pipe-separated text
    that parse_inquiry_document() can read.
    Preserves headers and all cell values.
    """
    import pandas as pd

    # Clean up
    df_clean = df.dropna(how="all").dropna(axis=1, how="all").fillna("")

    if df_clean.empty:
        return ""

    # Try to detect if first non-empty row is a header
    # If it contains text-heavy content (not all numbers), use it as header
    first_row = df_clean.iloc[0].astype(str).tolist()
    has_header = any(
        not _is_numeric(v) and len(v.strip()) > 1
        for v in first_row
    )

    lines = [f"Sheet: {sheet_name}"]
    lines.append("")

    if has_header:
        # Use first row as column headers
        headers = [str(v).strip() for v in first_row]
        lines.append(" | ".join(h for h in headers if h))
        lines.append("-" * 60)
        for _, row in df_clean.iloc[1:].iterrows():
            row_vals = [str(v).strip() for v in row.values]
            row_text  = " | ".join(row_vals)
            # Skip rows that are entirely empty
            if any(v for v in row_vals):
                lines.append(row_text)
    else:
        # No clear header — just dump rows as-is
        for _, row in df_clean.iterrows():
            row_vals = [str(v).strip() for v in row.values]
            if any(v for v in row_vals):
                lines.append(" | ".join(row_vals))

    result = "\n".join(lines)
    print(f"  Extracted {len(lines)} lines from sheet '{sheet_name}'")
    return result


def _is_numeric(val: str) -> bool:
    try:
        float(str(val).replace(",", "").replace("%", ""))
        return True
    except ValueError:
        return False


# ── Image formats — Groq vision ───────────────────────────────

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

MEDIA_TYPE_MAP = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp":  "image/bmp",
    ".gif":  "image/gif",
}


_IMAGE_PROMPT = (
    "Extract ALL text from this image exactly as it appears. "
    "If there is a table, preserve the columns and rows using "
    "pipe characters (|) to separate columns. "
    "Include every word, number, and reference visible. "
    "Do not summarize — output the raw text content only."
)


def extract_from_image(file_path: str) -> str:
    """
    Uses Claude Haiku vision (primary) → GPT-4o-mini (fallback) to read text from images.
    Groq is NOT used here — reserved for vendor discovery.
    """
    from services.openai_fallback import parse_with_llm_vision

    ext        = os.path.splitext(file_path)[1].lower()
    media_type = MEDIA_TYPE_MAP.get(ext, "image/jpeg")

    with open(file_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    data_url = f"data:{media_type};base64,{image_data}"
    return parse_with_llm_vision(data_url, _IMAGE_PROMPT, max_tokens=2000)


# ── Main entry point ──────────────────────────────────────────

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".xlsb"}

def extract_text(file_path: str) -> str:
    """
    Auto-detects file type and extracts text.
    Handles documents, images, and Excel files.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return extract_from_pdf(file_path)

    elif ext in (".docx", ".doc"):
        return extract_from_docx(file_path)

    elif ext in (".txt", ".csv"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    elif ext in EXCEL_EXTENSIONS:
        return extract_from_excel(file_path)

    elif ext in IMAGE_EXTENSIONS:
        return extract_from_image(file_path)

    else:
        raise Exception(
            f"Unsupported file type: {ext}. "
            f"Supported: PDF, DOCX, TXT, CSV, XLSX, XLS, PNG, JPG, JPEG, WEBP, BMP, GIF"
        )