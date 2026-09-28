"""Parse and validate the structured JSON returned by the AI.

The AI is treated like any untrusted input: nothing it returns is used until
it has been parsed, type-checked, trimmed, and checked against allowed values.
"""
import json
import re

# Allowed values belong to the business rules; the AI must pick from them.
from rules.business import DEPARTMENTS, PRIORITIES

# field -> (type, max length). Lists are lists of short strings.
STRING_FIELDS = {
    "summary": 500,
    "intent": 150,
    "next_action": 300,
    "followup_timeframe": 80,
    "email_subject": 150,
    "email_body": 3000,
}
LIST_FIELDS = {"key_details": 8, "missing_info": 8}
LIST_ITEM_MAX = 200


class AIError(Exception):
    """An AI problem with a message that is safe to show in the UI."""


def parse_json_text(text: str) -> dict:
    """Turn raw model text into a dict, tolerating ```json fences or stray prose."""
    if not text or not text.strip():
        raise AIError("The AI returned an empty response.")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise AIError("The AI response was not valid JSON.")
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            raise AIError("The AI response was not valid JSON.")
    if not isinstance(data, dict):
        raise AIError("The AI response was not a JSON object.")
    return data


def _match_choice(value, choices):
    if not isinstance(value, str):
        return None
    lookup = {c.lower(): c for c in choices}
    return lookup.get(value.strip().lower())


def validate_analysis(data: dict) -> dict:
    """Return a clean analysis dict or raise AIError describing what was wrong."""
    problems = []
    clean = {}

    for field, limit in STRING_FIELDS.items():
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"'{field}' is missing or not text")
            continue
        clean[field] = value.strip()[:limit]

    for field, max_items in LIST_FIELDS.items():
        value = data.get(field, [])
        if isinstance(value, str):  # tolerate a single string instead of a list
            value = [value] if value.strip() else []
        if not isinstance(value, list):
            problems.append(f"'{field}' must be a list")
            continue
        # Keep only plain text/number items; drop nulls, objects and nested lists.
        items = [str(v).strip()[:LIST_ITEM_MAX] for v in value
                 if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip()]
        clean[field] = list(dict.fromkeys(items))[:max_items]  # de-duplicate, keep order

    priority = _match_choice(data.get("priority"), PRIORITIES)
    if priority is None:
        problems.append("'priority' must be Low, Medium or High")
    clean["priority"] = priority

    # An unknown department is not fatal: the rules route by service instead.
    clean["department"] = _match_choice(data.get("department"), DEPARTMENTS)

    if problems:
        raise AIError("The AI response failed validation: " + "; ".join(problems) + ".")
    return clean
