"""Builds the "Why this decision?" panel: who decided each outcome, and why.

Everything is derived from stored values (AI suggestion, rule decision, human
override), so the explanation is always consistent with what the app did.
"""
from rules.business import follow_up_rule

AI, RULE, HUMAN = "AI", "Rule", "Human"


def _priority_row(lead: dict, ai_ok: bool) -> dict:
    if lead["human_priority"]:
        return {"label": "Priority", "value": lead["human_priority"], "sources": [HUMAN],
                "reason": f"Set by a person. The rules had decided {lead['rule_priority']}."}
    trace = lead["priority_reasons"] or []
    if trace and isinstance(trace[0], str):  # rows saved by an older version
        return {"label": "Priority", "value": lead["rule_priority"], "sources": [RULE], "reason": " ".join(trace)}
    raised = [t["rule"] for t in trace if t["raised"]]
    start = f"The AI read the message as {lead['ai_priority']}" if ai_ok else "AI was unavailable, so rules started at Medium"
    if raised:
        reason = f"{start}; raised because: " + "; ".join(raised) + "."
    else:
        reason = f"{start}; no business rule required a higher priority."
    return {"label": "Priority", "value": lead["rule_priority"], "sources": [RULE], "reason": reason}


def explain(lead: dict) -> list[dict]:
    ai_ok = lead["source"] != "fallback"
    ai_or_fallback = AI if ai_ok else RULE
    rows = [_priority_row(lead, ai_ok)]

    used_ai_routing = lead["service_interest"] == "Unsure" and ai_ok and lead["ai_department"] == lead["department"]
    rows.append({"label": "Department", "value": lead["department"], "sources": [AI if used_ai_routing else RULE],
                 "reason": lead["department_reason"] or "Routed by the service the customer selected."})

    date_reason = follow_up_rule(lead["priority"])
    if lead["human_priority"]:
        date_reason += " Recalculated after a person changed the priority."
    if ai_ok and lead["followup_timeframe"]:
        date_reason += f" The AI suggested “{lead['followup_timeframe']}” (not used)."
    rows.append({"label": "Follow-up date", "value": lead["follow_up_date"], "sources": [RULE],
                 "reason": date_reason, "is_date": True})

    if lead["human_next_action"]:
        rows.append({"label": "Next action", "value": "Changed", "sources": [HUMAN],
                     "reason": f"A person replaced the AI's suggestion: “{lead['ai_next_action']}”"})
    else:
        rows.append({"label": "Next action", "value": "Suggested", "sources": [ai_or_fallback],
                     "reason": "Suggested by the AI from the message. A person can change it."
                     if ai_ok else "Default action, because AI analysis was unavailable."})

    if lead["warnings"]:
        rows.append({"label": "Missing fields", "value": f"{len(lead['warnings'])} flagged", "sources": [RULE],
                     "reason": "Required-field checks on the submitted form. The AI doesn't decide what's missing."})

    rows.append({"label": "Summary & details", "value": lead["intent"], "sources": [ai_or_fallback],
                 "reason": "Interpreted from the customer's free-text message."
                 if ai_ok else "Generic text, because AI analysis was unavailable."})

    status = lead["email_status"]
    edited = " and edited" if lead["email_edited"] else ""
    email_reason = {
        "Pending review": f"Drafted by the AI{edited}. Waiting for a person to approve, edit or reject it.",
        "Approved": f"Drafted by the AI{edited} and approved by a person.",
        "Rejected": f"Drafted by the AI{edited} and rejected by a person.",
    }[status] + " Never sent automatically."
    rows.append({"label": "Email", "value": status, "sources": [ai_or_fallback, HUMAN], "reason": email_reason})
    return rows
