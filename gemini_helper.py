"""All AI calls live here (Groq + Gemini with automatic fallback).
Test this file on its own before touching the UI:

    python gemini_helper.py
"""
import os
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    _APP_DIR = Path(sys.executable).resolve().parent
else:
    _APP_DIR = Path(__file__).resolve().parent
for _env_name in (".env", "api.env"):
    _env_path = _APP_DIR / _env_name
    if _env_path.is_file():
        load_dotenv(dotenv_path=_env_path)
        break

# Models: change in .env or api.env if a name is retired (GEMINI_MODEL / GROQ_MODEL).
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GROQ_MODEL = os.getenv("GROQ_MODEL", "")  # leave empty to auto-pick from what your key can use
# Preferred Groq models, best first. The first one your account has is used.
GROQ_PREFERRED = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]
MODEL = GEMINI_MODEL  # kept for backwards compatibility

# Which provider to try first. Set PROVIDER_ORDER=gemini,groq in .env or api.env to change.
PROVIDER_ORDER = [p.strip() for p in os.getenv("PROVIDER_ORDER", "groq,gemini").split(",") if p.strip()]

# Free tiers have limits, so trim very long notes.
MAX_CHARS = 30000

# Errors worth retrying (server busy / rate limit / timeout).
_RETRYABLE = ("500", "502", "503", "504", "429", "UNAVAILABLE", "DEADLINE_EXCEEDED",
              "RESOURCE_EXHAUSTED", "INTERNAL", "rate limit", "Rate limit", "timed out", "Timeout", "timeout")

_clients = {}


class GeminiError(Exception):
    """Raised for any problem talking to the AI (shown to the user in the UI)."""


def _gemini_call(prompt):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise GeminiError("GEMINI_API_KEY is missing.")
    if "gemini" not in _clients:
        from google import genai
        from google.genai import types
        _clients["gemini"] = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60000))
    r = _clients["gemini"].models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return r.text or ""


def _pick_groq_model(client):
    """Ask Groq which models this key can use and choose the best match."""
    if GROQ_MODEL:
        return GROQ_MODEL
    if "groq_model" not in _clients:
        available = {m.id for m in client.models.list().data}
        chosen = next((m for m in GROQ_PREFERRED if m in available), None)
        if chosen is None:
            skip = ("whisper", "tts", "guard", "orpheus", "allam", "compound")
            chat_models = sorted(m for m in available if not any(x in m.lower() for x in skip))
            if not chat_models:
                raise GeminiError("No usable Groq chat model found for this key.")
            chosen = chat_models[0]
        print(f"  [groq] using model: {chosen}", flush=True)
        _clients["groq_model"] = chosen
    return _clients["groq_model"]


def _groq_call(prompt):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise GeminiError("GROQ_API_KEY is missing.")
    if "groq" not in _clients:
        from openai import OpenAI
        _clients["groq"] = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1", timeout=60)
    client = _clients["groq"]
    r = client.chat.completions.create(
        model=_pick_groq_model(client), messages=[{"role": "user", "content": prompt}], temperature=0.3
    )
    text = r.choices[0].message.content or ""
    if "</think>" in text:  # some models include their reasoning; drop it
        text = text.split("</think>")[-1]
    return text.strip()


_PROVIDERS = {"gemini": _gemini_call, "groq": _groq_call}


def _ask(prompt, retries=2):
    """Try each provider in order. Retry busy errors briefly, then fall back to the next provider."""
    errors = []
    for name in PROVIDER_ORDER:
        call = _PROVIDERS.get(name)
        if call is None:
            continue
        delay = 2
        for attempt in range(retries + 1):
            try:
                print(f"  [{name}] calling (attempt {attempt + 1})...", flush=True)
                return call(prompt)
            except Exception as e:
                msg = str(e)
                if "_KEY is missing" in msg:
                    errors.append(f"{name}: no API key")
                    break
                if any(c in msg for c in _RETRYABLE) and attempt < retries:
                    print(f"  [{name}] busy, retrying in {delay}s...", flush=True)
                    time.sleep(delay)
                    delay *= 2
                    continue
                errors.append(f"{name}: {msg[:150]}")
                print(f"  [{name}] failed, trying next provider...", flush=True)
                break
    raise GeminiError("All AI providers failed. " + " | ".join(errors))


def _trim(notes):
    return notes[:MAX_CHARS]


def _parse_json(text):
    """Pull a JSON list out of the model's reply, even if it adds extra text."""
    clean = text.replace("```json", "").replace("```", "").strip()
    start, end = clean.find("["), clean.rfind("]")
    if start == -1 or end == -1:
        raise GeminiError("Couldn't read the AI's response. Please try again.")
    try:
        data = json.loads(clean[start:end + 1])
    except json.JSONDecodeError:
        raise GeminiError("Couldn't read the AI's response. Please try again.")
    if not data:
        raise GeminiError("The AI returned nothing. Please try again.")
    return data


def summarize(notes):
    return _ask(f"Summarize these notes in clear bullet points for studying:\n\n{_trim(notes)}")


def make_flashcards(notes, n=5):
    prompt = (
        f"Create {n} flashcards from these notes. Respond ONLY with a JSON list "
        'like [{"question": "...", "answer": "..."}]. No extra text.\n\n'
        f"{_trim(notes)}"
    )
    cards = _parse_json(_ask(prompt))
    return [c for c in cards if isinstance(c, dict) and "question" in c and "answer" in c]


def make_quiz(notes, n=5):
    prompt = (
        f"Create {n} multiple-choice questions from these notes. Each has exactly 4 options. "
        "Respond ONLY with JSON in this format: "
        '[{"question": "...", "options": ["text1", "text2", "text3", "text4"], '
        '"answer_index": 0, "explanation": "..."}]. '
        "Options must be plain text with no A/B/C/D prefixes. answer_index is the 0-based "
        "position of the correct option. No extra text.\n\n"
        f"{_trim(notes)}"
    )
    quiz = _parse_json(_ask(prompt))
    valid = []
    for q in quiz:
        try:
            if len(q["options"]) == 4 and int(q["answer_index"]) in range(4):
                q["answer_index"] = int(q["answer_index"])
                q.setdefault("explanation", "")
                valid.append(q)
        except (KeyError, TypeError, ValueError):
            continue
    if not valid:
        raise GeminiError("Couldn't build a valid quiz. Please try again.")
    return valid


def chat(notes, question, history=None):
    past = ""
    for who, msg in (history or [])[-6:]:
        past += f"{who}: {msg}\n"
    return _ask(
        "Answer using ONLY these notes. If the answer isn't there, say so.\n\n"
        f"NOTES:\n{_trim(notes)}\n\n"
        f"CONVERSATION SO FAR:\n{past}\n"
        f"QUESTION: {question}"
    )


if __name__ == "__main__":
    print(f"Provider order: {PROVIDER_ORDER}", flush=True)
    sample = "Photosynthesis is the process by which plants convert light, water and CO2 into glucose and oxygen."
    print("\n--- SUMMARY ---\n" + summarize(sample), flush=True)
    print("\n--- FLASHCARDS ---\n", make_flashcards(sample, 2), flush=True)
    print("\n--- QUIZ ---\n", make_quiz(sample, 2), flush=True)
    print("\nAll tests passed.")