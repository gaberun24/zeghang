"""
OpenAI GPT-4o-mini integration — issue categorization, urgency, duplicate detection.
"""

import json
import openai
from lib.config import OPENAI_API_KEY, OPENAI_MODEL

_client = None

CATEGORIES = {
    "road": "Közút",
    "park": "Park / Zöldterület",
    "safety": "Biztonság",
    "infrastructure": "Infrastruktúra",
    "transport": "Közlekedés",
    "other": "Egyéb",
}

URGENCY_LABELS = {
    "low": "Alacsony",
    "medium": "Közepes",
    "high": "Magas",
    "urgent": "Sürgős",
}


def _get_client():
    global _client
    if _client is None:
        _client = openai.OpenAI(api_key=OPENAI_API_KEY)
    return _client


def categorize_issue(title: str, description: str = "") -> dict:
    """
    AI categorizes an issue. Returns:
    {"category": "road", "urgency": "medium", "reason": "..."}
    Falls back to {"category": "other", "urgency": "low"} on error.
    """
    if not OPENAI_API_KEY:
        return {"category": "other", "urgency": "low", "reason": "AI nem elérhető"}

    prompt = f"""Egy zalaegerszegi közösségi platformra érkezett bejelentés.
Kategorizáld és értékeld a sürgősségét.

Cím: {title}
Leírás: {description}

Válaszolj CSAK JSON-ban, semmi más:
{{
  "category": "road|park|safety|infrastructure|transport|other",
  "urgency": "low|medium|high|urgent",
  "reason": "rövid indoklás magyarul (max 1 mondat)"
}}"""

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        text = resp.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        if result.get("category") not in CATEGORIES:
            result["category"] = "other"
        if result.get("urgency") not in URGENCY_LABELS:
            result["urgency"] = "low"
        return result
    except Exception:
        return {"category": "other", "urgency": "low", "reason": "AI feldolgozási hiba"}


def check_duplicates(title: str, description: str, existing_issues: list) -> int | None:
    """
    Check if a new issue is a duplicate of an existing one.
    existing_issues: list of dicts with "id", "title", "description".
    Returns the ID of the duplicate issue, or None.
    """
    if not OPENAI_API_KEY or not existing_issues:
        return None

    issues_text = "\n".join(
        f"[ID:{i['id']}] {i['title']} — {i['description'][:100]}"
        for i in existing_issues[:50]
    )

    prompt = f"""Egy zalaegerszegi közösségi platformra érkezett ÚJ bejelentés:
Cím: {title}
Leírás: {description}

Meglévő nyitott bejelentések:
{issues_text}

Ha az új bejelentés egyértelműen ugyanarról a problémáról szól mint egy meglévő, válaszolj:
{{"duplicate_of": ID_SZÁM}}
Ha NEM duplikátum, válaszolj:
{{"duplicate_of": null}}

Válaszolj CSAK JSON-ban."""

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=50,
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        dup_id = result.get("duplicate_of")
        if dup_id is not None:
            return int(dup_id)
        return None
    except Exception:
        return None


def quick_categorize(title: str) -> str | None:
    """
    Fast categorization from title only (for AJAX autocomplete).
    Returns category key or None.
    """
    if not OPENAI_API_KEY or len(title) < 8:
        return None

    prompt = f"""Kategorizáld ezt a bejelentés címet:
"{title}"

Válaszolj EGYETLEN szóval: road, park, safety, infrastructure, transport, other"""

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=10,
        )
        cat = resp.choices[0].message.content.strip().lower()
        if cat in CATEGORIES:
            return cat
        return None
    except Exception:
        return None
