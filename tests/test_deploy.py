"""Tests for the public-deployment safeguards: site password and AI cost limit.

    python -m unittest tests.test_deploy -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ai.client as ai_client  # noqa: E402
import database as db  # noqa: E402
from app import create_app  # noqa: E402

LEAD = {"first_name": "Grace", "last_name": "Kim", "email": "g@example.com", "phone": "5125550131",
        "address": "2604 Hillcrest Ave", "monthly_bill": "480", "service_interest": "Solar",
        "message": "Just curious what solar might cost."}
VALID_AI = json.dumps({"summary": "S", "intent": "I", "priority": "Low", "department": "Solar Sales",
                       "next_action": "Call.", "key_details": [], "missing_info": [],
                       "followup_timeframe": "Soon", "email_subject": "Hi", "email_body": "Hi Grace"})


class DeployTestCase(unittest.TestCase):
    overrides = {}

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        config = {"DATABASE_PATH": self.db_path, "DEMO_MODE": True, "CSRF_DISABLED": True, "SECRET_KEY": "t"}
        config.update(self.overrides)
        self.client = create_app(config).test_client()

    def tearDown(self):
        os.remove(self.db_path)


class PasswordTests(DeployTestCase):
    overrides = {"APP_PASSWORD": "correct horse battery staple"}

    def test_every_page_requires_sign_in(self):
        for path in ["/", "/leads/new", "/leads/1"]:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)
            self.assertIn("/login", resp.headers["Location"])
        self.assertEqual(self.client.post("/leads", data=LEAD).status_code, 302)
        self.assertEqual(db.get_stats(self.db_path)["total"], 0)  # nothing got through

    def test_health_check_and_styles_stay_open(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/static/style.css").status_code, 200)

    def test_wrong_password(self):
        with mock.patch("auth.time.sleep") as slept:
            page = self.client.post("/login", data={"password": "guess"}).get_data(as_text=True)
        slept.assert_called_once()
        self.assertIn("password isn", page)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_sign_in_returns_to_requested_page_then_sign_out(self):
        resp = self.client.post("/login", data={"password": "correct horse battery staple", "next": "/leads/new"})
        self.assertEqual(resp.headers["Location"], "/leads/new")
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("Lead dashboard", page)
        self.assertIn("Sign out", page)
        self.client.get("/logout")
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_requested_page_survives_a_wrong_password(self):
        with mock.patch("auth.time.sleep"):
            page = self.client.post("/login", data={"password": "guess", "next": "/leads/3"}).get_data(as_text=True)
        self.assertIn('name="next" value="/leads/3"', page)

    def test_no_redirect_to_other_sites(self):
        resp = self.client.post("/login", data={"password": "correct horse battery staple",
                                                "next": "//evil.example.com"})
        self.assertEqual(resp.headers["Location"], "/")


class NoPasswordTests(DeployTestCase):
    def test_local_use_needs_no_sign_in(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("Lead dashboard", page)
        self.assertNotIn("Sign out", page)
        self.assertEqual(self.client.get("/login").status_code, 302)


class AiLimitTests(DeployTestCase):
    overrides = {"DEMO_MODE": False, "ANTHROPIC_API_KEY": "sk-test", "AI_HOURLY_LIMIT": 2}

    def setUp(self):
        super().setUp()
        ai_client._recent_calls.clear()

    def test_hourly_limit_falls_back_without_calling_the_api(self):
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"content": [{"type": "text", "text": VALID_AI}], "stop_reason": "end_turn"}
        with mock.patch.object(ai_client.requests, "post", return_value=ok) as post:
            for _ in range(3):
                self.client.post("/leads", data=LEAD)
        self.assertEqual(post.call_count, 2)                      # third lead never reached the API
        self.assertEqual(db.get_lead(self.db_path, 1)["source"], "llm")
        third = db.get_lead(self.db_path, 3)
        self.assertEqual(third["source"], "fallback")
        self.assertIn("hourly AI limit", third["ai_error"])
        self.assertEqual(third["priority"], "High")               # rules still work: $480 bill


if __name__ == "__main__":
    unittest.main()
