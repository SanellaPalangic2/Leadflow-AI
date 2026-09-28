"""The lead-processing workflow, showing who does what.

    1. RULES   validate the form                         (app.py -> rules/validation.py)
    2. AI      interpret the free-text message           (ai/)
    3. RULES   check the AI output, then decide           (ai/schema.py, rules/business.py)
               priority, routing, warnings, follow-up date
    4. SAVE    original lead + AI output + decisions     (database.py)
    5. HUMAN   approve/edit/reject email, override        (human/review.py, later, in the UI)
               priority, change next action, set status
"""
import logging
from datetime import date

import ai.client
import ai.demo
from ai.schema import AIError, parse_json_text, validate_analysis
from database import save_lead_with_analysis
from rules.business import apply_rules
from rules.fallback import fallback_analysis

log = logging.getLogger(__name__)


def interpret_with_ai(lead: dict, config) -> tuple[dict, str, str | None, str | None]:
    """Step 2-3a: language understanding, validated. Returns (analysis, source, raw, error).

    Never raises: if the AI fails in any way, a deterministic fallback keeps the
    workflow moving and the lead is flagged for manual review.
    """
    source = "demo" if config.DEMO_MODE else "llm"
    raw = None
    try:
        raw = ai.demo.generate_raw_response(lead, config) if config.DEMO_MODE \
            else ai.client.request_analysis(lead, config)
        return validate_analysis(parse_json_text(raw)), source, raw, None
    except AIError as exc:
        log.warning("AI analysis failed, using fallback: %s", exc)
        error = str(exc)
    except Exception:  # an unexpected bug must not lose the customer's lead
        log.exception("Unexpected error during AI analysis")
        error = "An unexpected error occurred during AI analysis."
    return fallback_analysis(lead, config), "fallback", raw, error


def process_lead(lead: dict, config, today: date | None = None) -> dict:
    """Run steps 2-4 for one validated lead. Returns a small result dict."""
    analysis, source, raw, ai_error = interpret_with_ai(lead, config)
    decisions = apply_rules(lead, analysis, today)

    record = {
        "source": source,
        "ai_error": ai_error,
        # AI: language understanding
        "summary": analysis["summary"],
        "intent": analysis["intent"],
        "key_details": analysis["key_details"],
        "ai_next_action": analysis["next_action"],
        "followup_timeframe": analysis["followup_timeframe"],
        "email_subject": analysis["email_subject"],
        "email_body": analysis["email_body"],
        "raw_response": raw[:20000] if raw else None,
        # Rules: decisions (plus the AI suggestions they considered)
        **decisions,
    }
    lead_id = save_lead_with_analysis(config.DATABASE_PATH, lead, record)
    return {"lead_id": lead_id, "source": source, "ai_error": ai_error, "warnings": decisions["warnings"]}
