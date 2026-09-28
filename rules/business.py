"""Deterministic business rules: the decisions with business consequences.

The AI's output is treated as *input* here (for example its read of urgency),
never as the final word. Every decision records a plain-English reason, which
the "Why this decision?" panel shows.
"""
import re
from datetime import date, timedelta

# ---------- Business vocabulary (owned by the rules, not the AI) ----------
PRIORITIES = ["Low", "Medium", "High"]
PRIORITY_RANK = {p: i for i, p in enumerate(PRIORITIES)}
DEPARTMENTS = ["Solar Sales", "Roofing Services", "Solar & Roofing Projects", "Energy Consultation"]
DEPARTMENT_BY_SERVICE = {
    "Solar": "Solar Sales",
    "Roofing": "Roofing Services",
    "Solar + Roofing": "Solar & Roofing Projects",
    "Unsure": "Energy Consultation",
}

# ---------- Thresholds ----------
HIGH_BILL = 350      # $/month at or above -> High priority
ELEVATED_BILL = 200  # $/month at or above -> at least Medium
LOW_BILL = 80        # $/month below -> solar savings likely small
FOLLOW_UP_BUSINESS_DAYS = {"High": 1, "Medium": 3, "Low": 5}
NEEDS_BILL = ("Solar", "Solar + Roofing", "Unsure")

# A keyword safety net: these always mean "urgent", even if the AI misses it.
URGENT_WORDS = ("leak", "leaks", "leaking", "leaked", "leaky", "dripping", "water damage",
                "storm damage", "hail damage", "roof emergency", "emergency repair")

# "no leaks", "isn't leaking", "haven't had any leaks" should NOT count as a mention.
_NEGATED = re.compile(r"(?:\bno|\bnot|\bnever|\bwithout|n't)\s+(?:\w+\s+){0,2}$")

# Items the form already collects. Code checks these, so AI questions about them are dropped.
FORM_FIELD_WORDS = ("phone", "email", "e-mail", "address", "electric bill", "utility bill",
                    "monthly bill", "bill amount", "contact information")


def mentions(text: str, phrases) -> bool:
    """True if any phrase appears as whole words and isn't directly negated."""
    text = (text or "").lower()
    for phrase in phrases:
        for match in re.finditer(r"\b" + re.escape(phrase) + r"\b", text):
            if not _NEGATED.search(text[max(0, match.start() - 40):match.start()]):
                return True
    return False


# ---------- Individual rules ----------
def decide_priority(lead: dict, ai_urgency: str) -> tuple[str, list[dict]]:
    """Start from the AI's read of urgency; business rules can raise it, never lower it."""
    priority, trace = ai_urgency, []
    bill = lead.get("monthly_bill")

    def floor(level: str, rule: str):
        nonlocal priority
        raised = PRIORITY_RANK[level] > PRIORITY_RANK[priority]
        if raised:
            priority = level
        trace.append({"rule": rule, "level": level, "raised": raised})

    if bill is not None and bill >= HIGH_BILL:
        floor("High", f"Monthly bill of ${bill:,.0f} is at or above ${HIGH_BILL}")
    elif bill is not None and bill >= ELEVATED_BILL:
        floor("Medium", f"Monthly bill of ${bill:,.0f} is at or above ${ELEVATED_BILL}")
    if mentions(lead.get("message"), URGENT_WORDS):
        floor("High", "Message mentions a leak, storm damage or an emergency repair")
    if lead["service_interest"] == "Solar + Roofing":
        floor("Medium", "Combined solar + roofing projects are at least Medium")
    return priority, trace


def route_department(service: str, ai_department: str | None) -> tuple[str, str]:
    """Known services use a fixed routing table. Only 'Unsure' leans on the AI,
    because then the message is the only signal, and only from the approved list."""
    if service != "Unsure":
        return DEPARTMENT_BY_SERVICE[service], f"{service} leads always route to {DEPARTMENT_BY_SERVICE[service]}."
    if ai_department in DEPARTMENTS:
        return ai_department, "Service was “Unsure”, so the AI's reading of the message was used (from the approved list)."
    return DEPARTMENT_BY_SERVICE["Unsure"], "Service was “Unsure” with no clear signal, so it defaults to Energy Consultation."


def tags_for(lead: dict) -> list[str]:
    bill, service = lead.get("monthly_bill"), lead["service_interest"]
    tags = []
    if bill is not None and bill >= HIGH_BILL:
        tags.append("High bill")
    if mentions(lead.get("message"), URGENT_WORDS):
        tags.append("Urgent")
    if service == "Solar + Roofing":
        tags.append("Bundle opportunity")
    if service in ("Solar", "Solar + Roofing") and bill is not None and bill < LOW_BILL:
        tags.append("Low savings potential")
    return tags


def missing_field_warnings(lead: dict) -> list[str]:
    warnings = []
    if not lead.get("email"):
        warnings.append("No email address. The draft email can't be sent; follow up by phone.")
    if not lead.get("phone"):
        warnings.append("No phone number. Follow-up is limited to email.")
    if not lead.get("address"):
        warnings.append("No property address. It's needed before a site visit or quote.")
    if lead["service_interest"] in NEEDS_BILL and lead.get("monthly_bill") is None:
        warnings.append("No electric bill amount. It's needed to size a solar system.")
    return warnings


def add_business_days(start: date, days: int) -> date:
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            days -= 1
    return current


def follow_up_date(priority: str, received: date) -> str:
    return add_business_days(received, FOLLOW_UP_BUSINESS_DAYS[priority]).isoformat()


def follow_up_rule(priority: str) -> str:
    days = FOLLOW_UP_BUSINESS_DAYS[priority]
    return f"{priority} priority → {days} business day{'s' if days > 1 else ''} after the lead arrived (weekends skipped)."


def contextual_questions(items: list[str]) -> list[str]:
    """Keep only the AI's context questions (roof age, ownership, ...). Whether a
    form field is empty is a fact the code already knows, not an AI judgment."""
    return [i for i in items if not any(word in i.lower() for word in FORM_FIELD_WORDS)]


# ---------- All rules together ----------
def apply_rules(lead: dict, analysis: dict, today: date | None = None) -> dict:
    today = today or date.today()
    priority, trace = decide_priority(lead, analysis["priority"])
    department, department_reason = route_department(lead["service_interest"], analysis.get("department"))
    return {
        "ai_priority": analysis["priority"],
        "rule_priority": priority,
        "priority_reasons": trace,
        "ai_department": analysis.get("department"),
        "department": department,
        "department_reason": department_reason,
        "tags": tags_for(lead),
        "warnings": missing_field_warnings(lead),
        "follow_up_date": follow_up_date(priority, today),
        "missing_info": contextual_questions(analysis.get("missing_info", [])),
    }
