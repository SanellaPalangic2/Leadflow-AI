"""Application configuration, read from environment variables (.env)."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _path(name: str, default: str) -> str:
    """Relative paths are resolved against the project folder, not the current
    working directory, so the app and seed.py always use the same database."""
    path = Path(os.getenv(name, default) or default)
    return str(path if path.is_absolute() else BASE_DIR / path)


class Config:
    # When true, LeadFlow never calls the LLM and uses deterministic sample output.
    # Defaults to true so a missing or incomplete .env can't break a demo.
    DEMO_MODE = _bool("DEMO_MODE", True)

    # LLM settings. The key is only ever read from the environment.
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
    LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5"
    LLM_TIMEOUT_SECONDS = _int("LLM_TIMEOUT_SECONDS", 30)
    # Cost guard: max live AI calls per hour. Past this, leads use rule-based defaults. 0 = no limit.
    AI_HOURLY_LIMIT = _int("AI_HOURLY_LIMIT", 30)

    # Optional site password. When set, every page (except /healthz) requires signing in.
    # Leave empty for local use; set it on any public deployment that uses a real API key.
    APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()

    # Used to personalize AI-drafted emails.
    COMPANY_NAME = os.getenv("COMPANY_NAME", "Summit Solar & Roofing")
    SENDER_NAME = os.getenv("SENDER_NAME", "Jordan Reyes")

    DATABASE_PATH = _path("DATABASE_PATH", "leadflow.db")

    # Used to sign the session cookie (flash messages + CSRF token).
    # A random fallback keeps local demos working; set it explicitly in .env.
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = bool(os.getenv("RENDER"))  # HTTPS-only cookie when hosted on Render
    MAX_CONTENT_LENGTH = 64 * 1024  # a lead form is tiny; reject oversized requests

    TESTING = False
