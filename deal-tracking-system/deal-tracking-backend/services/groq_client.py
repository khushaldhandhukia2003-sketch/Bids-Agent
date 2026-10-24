# services/groq_client.py
import os
import time
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ── Groq API key rotation ─────────────────────────────────────
# Add GROQ_API_KEY_2, GROQ_API_KEY_3 etc in .env for more free quota.
# Keys are tried in order; exhausted keys are skipped for the session.
_ALL_KEYS = [k for k in [
    os.getenv("GROQ_API_KEY"),
    os.getenv("GROQ_API_KEY_2"),
    os.getenv("GROQ_API_KEY_3"),
] if k]

_key_index        = 0       # which key we're currently on
_key_exhausted_until: dict = {}  # key → epoch timestamp when it becomes usable again

def _get_client():
    """Return a Groq client for the first non-exhausted key, or None if all exhausted."""
    global _key_index
    now = time.time()
    for i in range(len(_ALL_KEYS)):
        idx = (_key_index + i) % len(_ALL_KEYS)
        key = _ALL_KEYS[idx]
        if now >= _key_exhausted_until.get(key, 0):
            _key_index = idx
            return Groq(api_key=key), key
    return None, None

# Legacy singleton (kept for imports that do `from services.groq_client import _client`)
_client = Groq(api_key=_ALL_KEYS[0]) if _ALL_KEYS else None


def ask_groq(
    prompt:     str,
    system:     str  = "You are an expert procurement intelligence agent. Always respond with valid JSON only.",
    json_mode:  bool = True,
    max_tokens: int  = 2000,
) -> str:
    """
    Call Groq (first priority — free tier). Supports:
      • Key rotation: cycles through GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3
      • Circuit breaker: once a key is 429-ed it is skipped for 1 hour automatically
      • Full fallback chain: OpenAI gpt-4o-mini → Claude Haiku → GPT-4o when all keys exhausted
    """
    client, active_key = _get_client()

    if client is None:
        # All Groq keys exhausted — go directly to paid fallback
        soonest = min(_key_exhausted_until.values(), default=0)
        wait    = max(0, int(soonest - time.time()))
        print(f"  ⚡ All Groq keys exhausted (next reset in ~{wait//60}m) — using paid fallback")
        from services.llm_router import ask_llm
        return ask_llm(prompt, system=system, json_mode=json_mode,
                       max_tokens=max_tokens, start_from="openai-mini")

    try:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            **kwargs,
        )
        return resp.choices[0].message.content

    except Exception as exc:
        msg = str(exc).lower()
        is_exhausted = any(p in msg for p in (
            "rate limit", "rate_limit", "quota", "too many requests",
            "429", "resource exhausted", "tokens per", "requests per",
            "exceeded", "overloaded", "capacity",
        ))

        if is_exhausted:
            # Circuit breaker: mark this key as exhausted for 1 hour
            _key_exhausted_until[active_key] = time.time() + 3600
            keys_left = sum(
                1 for k in _ALL_KEYS
                if time.time() >= _key_exhausted_until.get(k, 0)
            )
            print(f"  ⚠️  Groq key exhausted — circuit open 1h. "
                  f"{keys_left}/{len(_ALL_KEYS)} key(s) still available.")
            # Retry with the next available Groq key, or fall back to OpenAI
            return ask_groq(prompt, system=system, json_mode=json_mode, max_tokens=max_tokens)

        raise   # non-quota error — let it propagate normally


# ── Quick test ────────────────────────────────────────────────
if __name__ == "__main__":
    result = ask_groq('Return this JSON: {"status": "connected", "model": "llama-3.3-70b"}')
    print("✅ Groq connected:", result)
