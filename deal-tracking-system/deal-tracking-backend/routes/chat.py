import os
import json
from groq import Groq
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/chat", tags=["Chat"])

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SUMMARISE_AFTER = 6   # summarise older messages after every 6 exchanges
MAX_RECENT      = 3   # always keep last 3 message pairs in full


class ChatMessage(BaseModel):
    role:    str   # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message:         str
    history:         List[ChatMessage] = []   # last N messages from frontend
    summary:         Optional[str]     = None # rolling summary of older messages
    drawing_context: Optional[str]     = None # extracted drawing JSON as string
    stage:           Optional[str]     = None # active workflow stage


class ChatResponse(BaseModel):
    reply:       str
    new_summary: Optional[str] = None  # updated summary if summarisation happened
    should_summarise: bool      = False


def build_system_prompt(drawing_context: str, stage: str) -> str:
    stage_focus = {
        "inquiry":  "Focus on identifying the client, project scope, documents provided and special requirements.",
        "drawing":  "Focus on structural components, dimensions, fabrication requirements and drawing details.",
        "boq":      "Focus on quantities, item descriptions and any discrepancies between BOQ and drawings.",
        "material": "Focus on material types, grades, specifications and standards.",
        "takeoff":  "Focus on component quantities, sizes and units for cost estimation.",
        "weight":   "Focus on weight calculations, formulas and totals.",
        "scope":    "Focus on what is included and excluded in the scope of supply.",
        "review":   "Focus on completeness, accuracy, missing items and final recommendations.",
    }
    focus = stage_focus.get(stage, "Answer questions about the engineering document accurately.")

    base = f"""You are an expert Steel Fabrication Estimation Assistant for Bhatia Brothers.
You help engineers analyse technical documents, drawings, BOQs and specifications.
{focus}
Be concise, technical and precise. Use bullet points for lists.
If asked something not in the document, say so clearly."""

    if drawing_context:
        base += f"\n\nExtracted document data (use this to answer questions):\n{drawing_context[:2000]}"

    return base


def summarise_history(messages: List[ChatMessage], drawing_context: str) -> str:
    """Ask Groq to summarise older messages into 2-3 sentences."""
    if not messages:
        return ""
    try:
        history_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in messages])
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""Summarise this engineering document conversation in 2-3 sentences.
Focus on what was found, confirmed or decided. Be technical and specific.

Conversation:
{history_text}

Return only the summary, no preamble."""
            }]
        )
        return response.choices[0].message.content.strip()
    except Exception:
        # If summarisation fails, just return a simple fallback
        return f"Previously discussed {len(messages)} messages about the document."


@router.post("/message", response_model=ChatResponse)
def send_message(req: ChatRequest):
    try:
        system_prompt = build_system_prompt(req.drawing_context, req.stage)

        # ── Build messages array ──────────────────────────────
        messages = [{"role": "system", "content": system_prompt}]

        # Add rolling summary as context if it exists
        if req.summary:
            messages.append({
                "role": "assistant",
                "content": f"[Summary of earlier conversation: {req.summary}]"
            })

        # Add recent message history (last MAX_RECENT exchanges)
        recent = req.history[-(MAX_RECENT * 2):]  # *2 for user+assistant pairs
        for m in recent:
            messages.append({"role": m.role, "content": m.content})

        # Add current user message
        messages.append({"role": "user", "content": req.message})

        # ── Call Groq ─────────────────────────────────────────
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=800,
            messages=messages
        )
        reply = response.choices[0].message.content.strip()

        # ── Check if we need to summarise ────────────────────
        # Summarise when history is getting long (older messages beyond MAX_RECENT)
        new_summary    = None
        should_summarise = len(req.history) >= SUMMARISE_AFTER

        if should_summarise:
            # Summarise everything except the last MAX_RECENT messages
            older_messages = req.history[:-(MAX_RECENT * 2)]
            if older_messages:
                combined = req.summary + " " if req.summary else ""
                new_summary = combined + summarise_history(older_messages, req.drawing_context or "")

        return ChatResponse(
            reply=reply,
            new_summary=new_summary,
            should_summarise=should_summarise
        )

    except Exception as e:
        print(f"❌ CHAT ERROR: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))