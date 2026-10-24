"""
services/llm_router.py

Unified LLM router with automatic fallback chain.

When any LLM API is exhausted (rate limit 429, quota error, timeout, or
any other API error), the router automatically tries the next provider in
order — no manual intervention needed.

Fallback chain (low-cost → high-cost):
  1. Groq         llama-3.1-8b-instant      (free tier / very cheap, fast)
  2. OpenAI       gpt-4o-mini               (cheap, reliable)
  3. Anthropic    claude-haiku-4-5-20251001 (cheap Claude)
  4. OpenAI       gpt-4o                    (expensive, last resort)

Usage:
  from services.llm_router import ask_llm

  result = ask_llm(prompt)                    # uses chain from #1
  result = ask_llm(prompt, start_from="openai")  # skip Groq
  result = ask_llm(prompt, json_mode=True)    # expect JSON back
"""

import os
import re
import json
import time
import traceback
from typing import Optional

# ── Rate-limit error fingerprints ────────────────────────────────────────────

_RATE_LIMIT_PHRASES = (
    "rate limit",
    "rate_limit",
    "quota",
    "too many requests",
    "429",
    "resource exhausted",
    "tokens per",
    "requests per",
    "exceeded",
    "overloaded",
    "capacity",
    "context_length_exceeded",
    "model_overloaded",
)

def _is_exhausted(exc: Exception) -> bool:
    """Return True if the exception looks like a quota / rate-limit error."""
    msg = str(exc).lower()
    return any(p in msg for p in _RATE_LIMIT_PHRASES)


# ── Individual provider callers ───────────────────────────────────────────────

def _call_groq(prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
    from services.groq_client import _client
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = _client.chat.completions.create(
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


def _call_openai_mini(prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
    import openai
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = openai.OpenAI(api_key=api_key)
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.3,
        **kwargs,
    )
    return resp.choices[0].message.content.strip()


def _call_anthropic_haiku(prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    full_prompt = prompt
    if json_mode:
        full_prompt = prompt + "\n\nReturn ONLY valid JSON. No markdown, no explanation."
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": full_prompt}],
    )
    return resp.content[0].text.strip()


def _call_openai_gpt4o(prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
    import openai
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = openai.OpenAI(api_key=api_key)
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
        **kwargs,
    )
    return resp.choices[0].message.content.strip()


# ── Fallback chain ────────────────────────────────────────────────────────────

_PROVIDERS = [
    ("groq",           _call_groq),
    ("openai-mini",    _call_openai_mini),
    ("anthropic-haiku",_call_anthropic_haiku),
    ("openai-gpt4o",   _call_openai_gpt4o),
]

_PROVIDER_INDEX = {name: i for i, (name, _) in enumerate(_PROVIDERS)}


def ask_llm(
    prompt:     str,
    system:     str      = "You are an expert procurement intelligence agent. Always respond with valid JSON only.",
    json_mode:  bool     = True,
    max_tokens: int      = 2000,
    start_from: str      = "groq",   # which provider to start from
    retry_delay: float   = 1.0,      # seconds to wait before trying next provider
) -> str:
    """
    Call LLMs in fallback order. Automatically skips to the next provider
    on any rate-limit / quota / timeout error.

    Args:
        prompt:     The user prompt.
        system:     System message (default: procurement JSON agent).
        json_mode:  If True, instruct the model to return JSON.
        max_tokens: Max output tokens.
        start_from: Provider name to start from ('groq', 'openai-mini',
                    'anthropic-haiku', 'openai-gpt4o').
        retry_delay: Seconds to wait between provider attempts.

    Returns:
        Raw text response from the first provider that succeeds.

    Raises:
        RuntimeError if ALL providers fail.
    """
    start_idx = _PROVIDER_INDEX.get(start_from, 0)
    chain     = _PROVIDERS[start_idx:]
    errors    = []

    for name, caller in chain:
        try:
            print(f"  🤖 LLM router: trying {name}...")
            result = caller(prompt, system, json_mode, max_tokens)
            print(f"  ✅ LLM router: {name} succeeded")
            return result

        except Exception as exc:
            reason = "rate-limit/quota" if _is_exhausted(exc) else "error"
            print(f"  ⚠️  LLM router: {name} failed ({reason}): {str(exc)[:120]}")
            errors.append(f"{name}: {str(exc)[:120]}")

            if len(chain) > 1:          # more providers to try
                time.sleep(retry_delay)
            continue

    raise RuntimeError(
        f"All LLM providers exhausted. Errors:\n" + "\n".join(errors)
    )


def ask_llm_json(
    prompt:     str,
    system:     str  = "You are an expert procurement intelligence agent. Always respond with valid JSON only.",
    max_tokens: int  = 2000,
    start_from: str  = "groq",
) -> dict:
    """
    Like ask_llm but always returns a parsed dict/list.
    Strips markdown fences and retries JSON parse.
    Raises ValueError if no provider returns valid JSON.
    """
    raw = ask_llm(prompt, system=system, json_mode=True,
                  max_tokens=max_tokens, start_from=start_from)
    clean = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Try truncated recovery
        last = clean.rfind("},")
        if last > 0:
            try:
                return json.loads(clean[:last+1] + "]")
            except Exception:
                pass
        raise ValueError(f"LLM returned non-JSON output: {clean[:200]}")
