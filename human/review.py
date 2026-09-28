"""Actions that require a person. Nothing here is triggered automatically.

Human input is still checked by deterministic code, and a priority override
hands back to the rules to recalculate the follow-up date.
"""
from datetime import date

import database as db
from rules.business import PRIORITIES, follow_up_date

EMAIL_ACTIONS = {"approve": "Approved", "reject": "Rejected", "reopen": "Pending review"}
MAX_NEXT_ACTION = 300


class ReviewError(ValueError):
    """Invalid human input, with a message safe to show in the UI."""


def review_email(db_path: str, lead_id: int, action: str) -> str:
    """Approve, reject or reopen the AI-drafted email. Returns a confirmation message."""
    status = EMAIL_ACTIONS.get(action)
    if status is None:
        raise ReviewError("Unknown email action.")
    moved_to_reviewed = db.set_email_status(db_path, lead_id, status)
    message = {
        "Approved": "Email approved. Copy it into your email client to send; LeadFlow never sends automatically.",
        "Rejected": "Email draft rejected.",
        "Pending review": "Email draft moved back to review.",
    }[status]
    if moved_to_reviewed:
        message += " Lead status changed from New to Reviewed."
    return message


def edit_email(db_path: str, lead_id: int, subject: str, body: str) -> str:
    subject, body = (subject or "").strip(), (body or "").strip()
    if not subject or not body:
        raise ReviewError("The email needs both a subject and a body.")
    if len(subject) > 150 or len(body) > 5000:
        raise ReviewError("The email is too long.")
    db.update_email_draft(db_path, lead_id, subject, body)
    return "Email draft updated. It still needs approval."


def save_decisions(db_path: str, lead: dict, status: str, priority: str, next_action: str) -> str:
    """Apply a person's status, priority override and next action.

    `priority` is "" to let the rules decide. An override equal to the rules'
    result, or a next action equal to the AI's, is stored as "no override".
    """
    if status not in db.LEAD_STATUSES:
        raise ReviewError("Unknown status.")
    if priority not in ("", *PRIORITIES):
        raise ReviewError("Unknown priority.")
    next_action = (next_action or "").strip()
    if len(next_action) > MAX_NEXT_ACTION:
        raise ReviewError(f"Keep the next action under {MAX_NEXT_ACTION} characters.")

    human_priority = priority if priority and priority != lead["rule_priority"] else None
    human_next_action = next_action if next_action and next_action != lead["ai_next_action"] else None

    # Rules own dates: re-run the follow-up calculation for the effective priority.
    effective = human_priority or lead["rule_priority"]
    received = date.fromisoformat(lead["created_at"][:10])
    new_date = follow_up_date(effective, received)

    db.save_human_decisions(db_path, lead["id"], status, human_priority, human_next_action, new_date)

    changes = []
    if status != lead["status"]:
        changes.append(f"status set to {status}")
    if human_priority != lead["human_priority"]:
        changes.append(f"priority set to {human_priority} by you" if human_priority
                       else f"priority returned to the rules' decision ({lead['rule_priority']})")
        if new_date != lead["follow_up_date"]:
            changes.append("follow-up date recalculated")
    if human_next_action != lead["human_next_action"]:
        changes.append("next action updated" if human_next_action else "next action reset to the AI suggestion")
    return ("Saved: " + ", ".join(changes) + ".") if changes else "No changes to save."
