"""All Gemini calls live here. Test this file on its own before touching the UI:

    python gemini_helper.py
"""
import os
import json
from dotenv import load_dotenv
from google import genai

load_dotenv()

# Change the model in .env (GEMINI_MODEL=...) if this one is retired.
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# Free tier has limits, so trim very long notes.
MAX_CHARS = 30000

_client = None


class GeminiError(Exception):
    """Raised for any problem talking to Gemini (shown to the user in the UI)."""


def _get_client():
    global _client
    if _client is None:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise GeminiError("GEMINI_API_KEY is missing. Add it to your .env file.")
        _client = genai.Client(api_key=key)
    return _client


def _ask(prompt):
    try:
        response = _get_client().models.generate_content(model=MODEL, contents=prompt)
        return response.text or ""
    except GeminiError:
        raise
    except Exception as e:
        raise GeminiError(f"Gemini request failed: {e}")


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
    sample = "Photosynthesis is the process by which plants convert light, water and CO2 into glucose and oxygen."
    print(summarize(sample))
    print(make_flashcards(sample, 2))
    print(make_quiz(sample, 2))