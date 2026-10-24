"""
routes/ai_proxy.py

Generic AI proxy — ProcurementAgent.jsx calls POST /api/ai/chat
for Step 1 document parsing and Step 4 RFQ email generation.

Replaced Anthropic claude-sonnet with Groq llama-3.3-70b-versatile.
Response shape is identical so the frontend needs zero changes.
"""

from fastapi          import APIRouter, HTTPException
from pydantic         import BaseModel
from typing           import List, Optional
from services.groq_client import ask_groq

router = APIRouter(prefix="/ai", tags=["AI Proxy"])


class Message(BaseModel):
    role:    str
    content: str

class AIRequest(BaseModel):
    messages:   List[Message]
    max_tokens: int = 1000
    model:      Optional[str] = None   # ignored — always uses Groq


@router.post("/chat")
def ai_chat(req: AIRequest):
    """
    Generic AI proxy.
    Accepts the same request shape the frontend already sends.
    Returns the same response shape so frontend needs no changes.
    """
    try:
        # Combine all messages into a single prompt for ask_groq
        # System messages become a system prefix, user/assistant alternate normally
        system_parts = []
        prompt_parts = []

        for m in req.messages:
            if m.role == "system":
                system_parts.append(m.content)
            elif m.role == "user":
                prompt_parts.append(f"User: {m.content}")
            elif m.role == "assistant":
                prompt_parts.append(f"Assistant: {m.content}")

        system  = "\n".join(system_parts) if system_parts else (
            "You are a helpful procurement assistant. "
            "When asked to return JSON, return only valid JSON with no markdown."
        )
        prompt  = "\n".join(prompt_parts) if prompt_parts else req.messages[-1].content

        # Detect if the frontend expects JSON back
        # (Step 1 parsing and Step 4 RFQ generation both ask for JSON)
        expects_json = any(
            word in prompt.lower()
            for word in ["return only", "return json", "json array", "valid json", "json object"]
        )

        text = ask_groq(
            prompt     = prompt,
            system     = system,
            json_mode  = expects_json,
            max_tokens = req.max_tokens,
        )

        # Return identical shape to what the frontend expects from Anthropic
        return {
            "success": True,
            "content": [{"type": "text", "text": text}]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))