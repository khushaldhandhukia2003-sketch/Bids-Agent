import os
import re
import json
import shutil
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from services.documentParser import extract_text
from services.groq_client import _client as client

router = APIRouter(prefix="/document", tags=["Document Parsing"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_UPLOAD_MB = 20
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# ΓöÇΓöÇ Stage-specific prompts ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
STAGE_PROMPTS = {
    "inquiry": """You are reviewing an initial client inquiry document. Extract and structure the inquiry details.
Return JSON:
{
  "summary": "2-3 sentence overview of the inquiry",
  "documentInfo": { "dwgNo": "", "fileNo": "", "proposalNo": "", "scale": "", "size": "", "sheet": "", "rev": "" },
  "projectInfo": { "projectTitle": "", "dwgTitle": "", "company": "", "contractor": "", "vendor": "" },
  "revisionHistory": [{ "rev": "", "description": "", "drwn": "", "dsnD": "", "rvwD": "", "appD": "", "date": "" }],
  "inquiryScope": {
    "client": "", "projectName": "", "deliveryLocation": "", "requiredDate": "",
    "documentsProvided": [], "specialRequirements": ""
  }
}""",

    "drawing": """You are analysing an engineering drawing. Extract all structural and fabrication details.
Return JSON:
{
  "summary": "2-3 sentence overview of the drawing",
  "documentInfo": { "dwgNo": "", "fileNo": "", "proposalNo": "", "scale": "", "size": "", "sheet": "", "rev": "" },
  "projectInfo": { "projectTitle": "", "dwgTitle": "", "company": "", "contractor": "", "vendor": "" },
  "revisionHistory": [{ "rev": "", "description": "", "drwn": "", "dsnD": "", "rvwD": "", "appD": "", "date": "" }],
  "skidSizes": { "length": "", "width": "", "height": "", "weight": "" },
  "connections": [{ "tag": "", "type": "", "spec": "" }],
  "flowMeters": [{ "tag": "", "duty": "", "straight": { "upstream": "", "downstream": "" } }],
  "valves": [{ "tag": "", "type": "", "qty": 0, "location": "" }],
  "instruments": [{ "tag": "", "description": "" }],
  "analyzerSystems": [{ "tag": "", "description": "", "location": "" }],
  "reducers": [{ "description": "", "location": "" }],
  "pipingDistances": [{ "ref": "", "distance": "" }],
  "drawingAnalysis": {
    "overallDesign": "", "dimensions": "", "structuralComponents": [],
    "weldingRequirements": "", "fabricationNotes": ""
  }
}""",

    "boq": """You are cross-verifying a Bill of Quantities against engineering drawings.
Return JSON:
{
  "summary": "2-3 sentence overview of the BOQ verification",
  "documentInfo": { "dwgNo": "", "fileNo": "", "proposalNo": "", "scale": "", "size": "", "sheet": "", "rev": "" },
  "projectInfo": { "projectTitle": "", "dwgTitle": "", "company": "", "contractor": "", "vendor": "" },
  "boqItems": [{ "itemNo": "", "description": "", "unit": "", "quantity": 0, "remarks": "" }],
  "discrepancies": [{ "item": "", "issue": "", "severity": "high/medium/low" }],
  "missingItems": [],
  "boqSummary": { "totalItems": 0, "flaggedItems": 0, "verificationStatus": "" }
}""",

    "material": """You are identifying all materials required from this engineering document.
Return JSON:
{
  "summary": "2-3 sentence overview of material requirements",
  "documentInfo": { "dwgNo": "", "fileNo": "", "proposalNo": "", "scale": "", "size": "", "sheet": "", "rev": "" },
  "projectInfo": { "projectTitle": "", "dwgTitle": "", "company": "", "contractor": "", "vendor": "" },
  "materials": [{ "component": "", "materialType": "", "grade": "", "spec": "", "form": "", "remarks": "" }],
  "materialSummary": { "primaryMaterial": "", "steelGrades": [], "surfaceTreatment": "", "specialRequirements": "" }
}""",

    "takeoff": """You are performing a quantity take-off from this engineering document.
Return JSON:
{
  "summary": "2-3 sentence overview of the quantity take-off",
  "documentInfo": { "dwgNo": "", "fileNo": "", "proposalNo": "", "scale": "", "size": "", "sheet": "", "rev": "" },
  "projectInfo": { "projectTitle": "", "dwgTitle": "", "company": "", "contractor": "", "vendor": "" },
  "quantityItems": [{ "tag": "", "description": "", "type": "", "size": "", "quantity": 0, "unit": "", "remarks": "" }],
  "takeoffSummary": { "totalLineItems": 0, "hiddenFabricationItems": [], "estimatedTotalWeight": "" }
}""",

    "weight": """You are calculating material weights from this engineering document.
Return JSON:
{
  "summary": "2-3 sentence overview of weight calculations",
  "documentInfo": { "dwgNo": "", "fileNo": "", "proposalNo": "", "scale": "", "size": "", "sheet": "", "rev": "" },
  "projectInfo": { "projectTitle": "", "dwgTitle": "", "company": "", "contractor": "", "vendor": "" },
  "skidSizes": { "length": "", "width": "", "height": "", "weight": "" },
  "weightCalculations": [{ "component": "", "material": "", "dimensions": "", "formula": "", "calculatedWeight": "", "unit": "kg" }],
  "weightSummary": { "totalStructuralWeight": "", "totalPipingWeight": "", "totalInstrumentWeight": "", "grandTotal": "", "weightBasis": "" }
}""",

    "scope": """You are confirming the scope of supply from this engineering document.
Return JSON:
{
  "summary": "2-3 sentence overview of scope confirmation",
  "documentInfo": { "dwgNo": "", "fileNo": "", "proposalNo": "", "scale": "", "size": "", "sheet": "", "rev": "" },
  "projectInfo": { "projectTitle": "", "dwgTitle": "", "company": "", "contractor": "", "vendor": "" },
  "scopeItems": [{ "activity": "", "included": true, "description": "", "remarks": "" }],
  "scopeSummary": { "rawMaterialSupply": "", "fabrication": "", "machining": "", "surfaceTreatment": "", "assembly": "", "packaging": "", "testing": "", "documentation": "" },
  "exclusions": [],
  "assumptions": []
}""",

    "review": """You are performing a final review of this estimation document.
Return JSON:
{
  "summary": "2-3 sentence overview of the final review",
  "documentInfo": { "dwgNo": "", "fileNo": "", "proposalNo": "", "scale": "", "size": "", "sheet": "", "rev": "" },
  "projectInfo": { "projectTitle": "", "dwgTitle": "", "company": "", "contractor": "", "vendor": "" },
  "reviewChecklist": [{ "checkItem": "", "status": "pass/fail/warning", "finding": "", "recommendation": "" }],
  "reviewSummary": { "missingComponents": [], "incorrectQuantities": [], "scopeClarity": "", "costAccuracy": "", "overallStatus": "approved/needs-revision/rejected", "finalRemarks": "" }
}""",
}

DEFAULT_PROMPT = STAGE_PROMPTS["drawing"]


@router.post("/parse")
async def parse_document(
    file:        UploadFile = File(...),
    stage:       str        = Form("drawing"),
    user_prompt: str        = Form(""),
):
    # -- Validate file type
    allowed = [".pdf", ".docx", ".doc", ".txt"]
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"File type {ext} not supported. Use: {allowed}")

    # -- Save uploaded file with size limit
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        total = 0
        chunk_size = 1024 * 64
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                f.close()
                os.remove(file_path)
                raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_UPLOAD_MB}MB allowed.")
            f.write(chunk)

    try:
        # ΓöÇΓöÇ Extract text ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        raw_text = extract_text(file_path)
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from document")

        # ΓöÇΓöÇ Get stage prompt ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        stage_instruction = STAGE_PROMPTS.get(stage, DEFAULT_PROMPT)

        # ── Call OpenAI/Claude for better document understanding ──
        # GPT-4o-mini understands engineering docs better than Groq llama.
        # Claude Haiku is the fallback if OpenAI is unavailable.
        from services.llm_router import ask_llm
        raw_result = ask_llm(
            prompt=f"""{stage_instruction}

{f'User request: "{user_prompt}"' if user_prompt else ""}

Return ONLY the JSON. No markdown, no explanation.

Raw document text:
{raw_text[:4000]}""",
            system="You are an expert engineering document analyst. Extract structured data and return ONLY valid JSON matching the schema provided.",
            json_mode=True,
            max_tokens=1500,
            start_from="openai-mini",
        )
        clean = re.sub(r"```json|```", "", raw_result).strip()
        data  = json.loads(clean)

        return { "success": True, "stage": stage, "filename": file.filename, "data": data }

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"AI returned invalid JSON: {e}")
    except Exception as e:
        print(f"Γ¥î DOCUMENT PARSE ERROR: {type(e).__name__}: {e}")  # ΓåÉ prints full error
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
