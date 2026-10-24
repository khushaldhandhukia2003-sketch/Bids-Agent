from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
from services.drawingExtractor import extract_dimensions

router = APIRouter()

# deal-tracking-backend folder
BASE_DIR = Path(__file__).resolve().parent.parent

# uploads folder inside backend
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

@router.post("/upload-drawing")
async def upload_drawing(file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file name received")

        file_path = UPLOAD_DIR / file.filename

        # Save uploaded file
        with open(file_path, "wb") as f:
            f.write(await file.read())

        # Process file
        dimensions = extract_dimensions(str(file_path))

        return {
            "filename": file.filename,
            "saved_path": str(file_path),
            "dimensions": dimensions
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))