"""LeadFlow web app: HTTP routes only.

Decisions live in three layers: rules/ (deterministic), ai/ (language tasks)
and human/ (approvals and overrides). pipeline.py runs the first two.
"""
import logging
import secrets
from datetime import date, datetime
from types import SimpleNamespace

from flask import (Flask, abort, current_app, flash, redirect, render_template,
                   request, session, url_for)

import database as db
from auth import init_auth
from config import Config
from explain import explain
from human import review
from pipeline import process_lead
from rules.business import PRIORITIES
from rules.validation import SERVICE_OPTIONS, validate_lead_form

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("leadflow")


def settings() -> SimpleNamespace:
    """App config as attributes, for the plain-Python modules."""
    return SimpleNamespace(**current_app.config)


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    db.init_db(app.config["DATABASE_PATH"])

    # Startup self-check, so a misconfigured demo is obvious in the terminal.
    # The key itself is never logged, only whether one is present.
    ai_ready = app.config["DEMO_MODE"] or bool(app.config["ANTHROPIC_API_KEY"])
    log.info("LeadFlow starting: DEMO_MODE=%s, model=%s, database=%s",
             app.config["DEMO_MODE"], app.config["LLM_MODEL"], app.config["DATABASE_PATH"])
    if not ai_ready:
        log.warning("DEMO_MODE is off but ANTHROPIC_API_KEY is empty: every lead will use the rule-based fallback.")
    if not app.config["DEMO_MODE"] and not app.config.get("APP_PASSWORD"):
        log.warning("Live AI is on without APP_PASSWORD: anyone who can reach this site can use your API credits.")
    log.info("Site password: %s. AI hourly limit: %s.",
             "on" if app.config.get("APP_PASSWORD") else "off", app.config.get("AI_HOURLY_LIMIT") or "none")

    # ---------- Security: simple CSRF protection for every POST ----------
    def csrf_token() -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    @app.before_request
    def check_csrf():
        if request.method != "POST" or app.config.get("CSRF_DISABLED"):
            return None
        sent = request.form.get("csrf_token", "").encode()
        expected = session.get("csrf_token", "").encode()
        if sent and expected and secrets.compare_digest(sent, expected):
            return None
        if request.endpoint == "create_lead":
            # Session expired (e.g. the server restarted): keep what the user typed.
            flash("Your session expired, so nothing was saved yet. Please submit the form again.", "warning")
            return render_template("new_lead.html", form=request.form, errors={}, services=SERVICE_OPTIONS), 400
        abort(400)

    @app.context_processor
    def inject_globals():
        return {"csrf_token": csrf_token, "demo_mode": app.config["DEMO_MODE"], "ai_ready": ai_ready,
                "today": date.today().isoformat()}

    init_auth(app)  # optional site password (APP_PASSWORD)

    # ---------- Template helpers ----------
    @app.template_filter("nice_date")
    def nice_date(value: str) -> str:
        try:
            d = date.fromisoformat(value[:10])
        except (TypeError, ValueError):
            return value or ""
        return d.strftime("%b %d, %Y").replace(" 0", " ")

    @app.template_filter("due_label")
    def due_label(value: str) -> str:
        try:
            days = (date.fromisoformat(value) - date.today()).days
        except (TypeError, ValueError):
            return ""
        if days < 0:
            return f"Overdue by {-days} day{'s' if days < -1 else ''}"
        return {0: "Due today", 1: "Due tomorrow"}.get(days, f"Due in {days} days")

    @app.template_filter("nice_datetime")
    def nice_datetime(value: str) -> str:
        try:
            dt = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return value or ""
        return dt.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")

    # ---------- Routes ----------
    @app.get("/")
    def dashboard():
        path = app.config["DATABASE_PATH"]
        return render_template("dashboard.html", stats=db.get_stats(path), leads=db.list_leads(path))

    @app.get("/leads/new")
    def new_lead():
        return render_template("new_lead.html", form={}, errors={}, services=SERVICE_OPTIONS)

    @app.post("/leads")
    def create_lead():
        lead, errors = validate_lead_form(request.form)
        if errors:
            flash("Please fix the highlighted fields.", "error")
            return render_template("new_lead.html", form=request.form, errors=errors,
                                   services=SERVICE_OPTIONS), 422

        try:
            result = process_lead(lead, settings())
        except Exception:
            # AI failures are already handled inside the pipeline; this catches
            # anything else (e.g. the database is locked) without losing the form.
            log.exception("Failed to process lead")
            flash("We couldn't save this lead because of an internal error. Your entries are still "
                  "below; please try again.", "error")
            return render_template("new_lead.html", form=request.form, errors={},
                                   services=SERVICE_OPTIONS), 500

        if result["source"] == "fallback":
            flash(f"Lead saved, but AI analysis was unavailable: {result['ai_error']} "
                  "A rule-based fallback was used, so please review this lead manually.", "warning")
        else:
            flash("Lead processed and saved. Review the AI analysis and email draft below.", "success")
        return redirect(url_for("lead_detail", lead_id=result["lead_id"]))

    @app.get("/leads")
    def leads_index():
        # e.g. the user presses Enter in the address bar after a validation error
        return redirect(url_for("dashboard"))

    @app.get("/leads/<int:lead_id>")
    def lead_detail(lead_id: int):
        lead = db.get_lead(app.config["DATABASE_PATH"], lead_id)
        if lead is None:
            abort(404)
        return render_template("lead_detail.html", lead=lead, statuses=db.LEAD_STATUSES,
                               priorities=PRIORITIES, decisions=explain(lead))

    # ---------- Human decisions (layer 3) ----------
    @app.post("/leads/<int:lead_id>/decisions")
    def save_decisions(lead_id: int):
        lead = _require_lead(lead_id)
        try:
            message = review.save_decisions(app.config["DATABASE_PATH"], lead, request.form.get("status", ""),
                                            request.form.get("priority", ""), request.form.get("next_action", ""))
            flash(message, "success")
        except review.ReviewError as exc:
            flash(str(exc), "error")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    @app.post("/leads/<int:lead_id>/email/edit")
    def edit_email(lead_id: int):
        _require_lead(lead_id)
        try:
            flash(review.edit_email(app.config["DATABASE_PATH"], lead_id, request.form.get("email_subject"),
                                    request.form.get("email_body")), "success")
        except review.ReviewError as exc:
            flash(str(exc), "error")
        return redirect(url_for("lead_detail", lead_id=lead_id) + "#email")

    @app.post("/leads/<int:lead_id>/email/<action>")
    def review_email(lead_id: int, action: str):
        _require_lead(lead_id)
        if action not in review.EMAIL_ACTIONS:
            abort(404)
        flash(review.review_email(app.config["DATABASE_PATH"], lead_id, action), "success")
        return redirect(url_for("lead_detail", lead_id=lead_id) + "#email")

    def _require_lead(lead_id: int) -> dict:
        lead = db.get_lead(app.config["DATABASE_PATH"], lead_id)
        if lead is None:
            abort(404)
        return lead

    # ---------- Friendly errors (never show stack traces) ----------
    @app.errorhandler(400)
    def bad_request(_):
        return render_template("error.html", title="Request expired",
                               message="Your session may have expired. Please reload the page and try again."), 400

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", title="Not found",
                               message="We couldn't find that page or lead."), 404

    @app.errorhandler(405)
    def method_not_allowed(_):
        return render_template("error.html", title="Page not available",
                               message="That address can't be opened directly. Use the links in the app."), 405

    @app.errorhandler(413)
    def too_large(_):
        return render_template("error.html", title="Submission too large",
                               message="That submission was too large. Please shorten the message."), 413

    @app.errorhandler(500)
    def server_error(_):
        return render_template("error.html", title="Something went wrong",
                               message="An unexpected error occurred. It has been logged; please try again."), 500

    return app


if __name__ == "__main__":
    # Debug stays off so errors never render a stack trace in the browser.
    # Port 5001 because macOS uses 5000 for AirPlay Receiver.
    create_app().run(debug=False, port=5001)
