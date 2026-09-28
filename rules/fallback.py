"""Deterministic stand-in used when the AI is unavailable or its output is invalid.

Keeps the workflow moving without AI: the lead is still saved, routed and
scheduled by the rules, and a person reviews a generic email draft.
"""
from rules.business import DEPARTMENT_BY_SERVICE


def fallback_analysis(lead: dict, config) -> dict:
    service = lead["service_interest"]
    first = lead["first_name"]
    return {
        "summary": f"{first} {lead['last_name']} submitted an inquiry about {service.lower()}. "
                   "AI analysis was unavailable, so this lead needs a manual review.",
        "intent": "Needs manual review",
        "priority": "Medium",
        "department": DEPARTMENT_BY_SERVICE[service],
        "next_action": "Read the original message and call the lead to qualify them.",
        "key_details": [],
        "missing_info": [],
        "followup_timeframe": "Not available",
        "email_subject": "Thanks for contacting us",
        "email_body": (
            f"Hi {first},\n\nThank you for reaching out to {config.COMPANY_NAME} about "
            f"{service.lower()}. I'd love to learn more about your home and what you're looking for.\n\n"
            "Could you reply with a couple of times that work for a short call?\n\n"
            f"Best regards,\n{config.SENDER_NAME}\n{config.COMPANY_NAME}"
        ),
    }
