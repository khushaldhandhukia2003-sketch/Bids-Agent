from fastapi import APIRouter
from services.geometryCalculator import cylinder_weight

router = APIRouter()

@router.post("/ask")
def ask_question(question:str, dimensions:dict):

    if "weight" in question:
        return cylinder_weight(
            dimensions["diameter"],
            dimensions["length"]
        )