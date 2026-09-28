"""Optional password protection for a public deployment.

If APP_PASSWORD is set, every page requires signing in once per browser
session. If it's empty (the default for local use), nothing changes.
"""
import secrets
import time

from flask import flash, redirect, render_template, request, session, url_for

OPEN_ENDPOINTS = {"login", "healthz", "static"}


def _safe_next(target: str | None) -> str:
    """Only allow redirects back into this site (prevents open redirects)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("dashboard")


def init_auth(app) -> None:
    @app.get("/healthz")
    def healthz():
        # Used by Render to check the app is up; reveals nothing.
        return "ok", 200

    @app.before_request
    def require_login():
        if not app.config.get("APP_PASSWORD") or request.endpoint in OPEN_ENDPOINTS:
            return None
        if session.get("signed_in"):
            return None
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        password = app.config.get("APP_PASSWORD")
        if not password:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            attempt = request.form.get("password", "").encode()
            if secrets.compare_digest(attempt, password.encode()):
                session.clear()
                session["signed_in"] = True
                return redirect(_safe_next(request.form.get("next")))
            time.sleep(1)  # slows down password guessing
            flash("That password isn't right.", "error")
        return render_template("login.html", next=request.values.get("next", "")), 200

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.context_processor
    def inject_auth():
        return {"auth_enabled": bool(app.config.get("APP_PASSWORD")), "signed_in": session.get("signed_in", False)}
