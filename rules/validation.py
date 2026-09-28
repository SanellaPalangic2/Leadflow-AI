"""Validation and cleaning of the lead intake form."""
import re

SERVICE_OPTIONS = ["Solar", "Roofing", "Solar + Roofing", "Unsure"]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MAX_LENGTHS = {
    "first_name": 60,
    "last_name": 60,
    "email": 120,
    "phone": 30,
    "address": 200,
    "message": 2000,
}


def validate_lead_form(form) -> tuple[dict, dict]:
    """Return (clean_data, errors). `errors` maps field name -> message."""
    data = {field: (form.get(field) or "").strip() for field in MAX_LENGTHS}
    data["service_interest"] = (form.get("service_interest") or "").strip()
    bill_raw = (form.get("monthly_bill") or "").strip()
    errors = {}

    for field, limit in MAX_LENGTHS.items():
        if len(data[field]) > limit:
            errors[field] = f"Please keep this under {limit} characters."

    if not data["first_name"]:
        errors["first_name"] = "First name is required."
    if not data["last_name"]:
        errors["last_name"] = "Last name is required."

    # At least one way to reach the lead is required. Missing the *other*
    # channel is allowed but produces a warning later (see rules.py).
    if not data["email"] and not data["phone"]:
        errors["email"] = "Provide an email or a phone number so we can follow up."
    if data["email"] and not EMAIL_RE.match(data["email"]):
        errors["email"] = "That email address doesn't look valid."
    if data["phone"]:
        digits = re.sub(r"\D", "", data["phone"])
        if not 7 <= len(digits) <= 15:
            errors["phone"] = "Phone number should contain 7 to 15 digits."

    if data["service_interest"] not in SERVICE_OPTIONS:
        errors["service_interest"] = "Please choose a service."

    data["monthly_bill"] = None
    if bill_raw:
        bill = parse_bill(bill_raw)
        if bill is None:
            errors["monthly_bill"] = "Enter the monthly bill as a single number, e.g. 180."
        else:
            data["monthly_bill"] = bill

    return data, errors


def parse_bill(raw: str) -> float | None:
    """Accept what people actually type: '180', '$1,200', '~250/mo', 'about 300 a month'."""
    text = raw.strip().lower()
    text = re.sub(r"^(about|around|approx\.?|approximately|roughly|~)\s*", "", text)
    text = re.sub(r"\s*(/\s*mo(nth)?|per\s+month|a\s+month|monthly)\.?$", "", text)
    text = re.sub(r"[\s$,]", "", text)
    if not re.fullmatch(r"\d+(\.\d+)?", text):  # rejects 'nan', 'inf', '1e5', ranges
        return None
    bill = float(text)
    return round(bill, 2) if bill <= 20000 else None
