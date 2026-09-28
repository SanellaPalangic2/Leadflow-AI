"""Run the five demo scenarios through the full HTTP workflow and check the outcome.

    python -m unittest tests.test_scenarios -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai.client as ai_client  # noqa: E402
import database as db  # noqa: E402
from app import create_app  # noqa: E402
from rules.business import add_business_days  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402


class ScenarioTests(unittest.TestCase):
    demo_mode = True

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = create_app({"DATABASE_PATH": self.db_path, "DEMO_MODE": self.demo_mode,
                               "CSRF_DISABLED": True, "SECRET_KEY": "t", "ANTHROPIC_API_KEY": "sk-test"})
        self.client = self.app.test_client()

    def tearDown(self):
        os.remove(self.db_path)

    def run_scenario(self, scenario):
        resp = self.client.post("/leads", data=scenario["form"])
        self.assertEqual(resp.status_code, 302, "lead should be accepted")
        lead_id = int(resp.headers["Location"].rsplit("/", 1)[-1])
        page = self.client.get(f"/leads/{lead_id}")
        self.assertEqual(page.status_code, 200)
        return db.get_lead(self.db_path, lead_id), page.get_data(as_text=True)

    def check(self, lead, page, exp):
        joined = lambda items: " | ".join(items)  # noqa: E731
        self.assertEqual(lead["priority"], exp["priority"])
        self.assertEqual(lead["department"], exp["department"])
        self.assertEqual(lead["status"], "New")
        self.assertEqual(lead["email_status"], "Pending review")
        expected_date = add_business_days(date.today(), exp["follow_up_business_days"]).isoformat()
        self.assertEqual(lead["follow_up_date"], expected_date)
        if "warnings" in exp:
            self.assertEqual(lead["warnings"], exp["warnings"])
        for w in exp.get("warnings_include", []):
            self.assertIn(w, joined(lead["warnings"]))
        for t in exp.get("tags_include", []):
            self.assertIn(t, lead["tags"])
        for t in exp.get("tags_exclude", []):
            self.assertNotIn(t, lead["tags"])
        if "monthly_bill" in exp:
            self.assertEqual(lead["monthly_bill"], exp["monthly_bill"])
        if "intent" in exp:
            self.assertEqual(lead["intent"], exp["intent"])
        for d in exp.get("details_include", []):
            self.assertIn(d, lead["key_details"])
        for d in exp.get("details_exclude", []):
            self.assertNotIn(d, joined(lead["key_details"]))
        for m in exp.get("missing_include", []):
            self.assertIn(m, joined(lead["missing_info"]))
        for m in exp.get("missing_exclude", []):
            self.assertNotIn(m, joined(lead["missing_info"]))
        if "email_includes" in exp:
            self.assertIn(exp["email_includes"], lead["email_body"])
        self.assertTrue(lead["email_body"].startswith(f"Hi {lead['first_name']}"))
        self.assertIn(lead["summary"], page)
        self.assertIn("Approve", page)

    def test_scenarios_in_demo_mode(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario["name"]):
                lead, page = self.run_scenario(scenario)
                self.assertEqual(lead["source"], "demo")
                self.check(lead, page, scenario["expect"])

    def test_scenario_review_actions(self):
        """Approve #1, edit #2, reject #3, then move #1 through the full status lifecycle."""
        for s in SCENARIOS[:3]:
            self.run_scenario(s)
        self.client.post("/leads/1/email/approve")
        self.client.post("/leads/2/email/edit", data={"email_subject": "Roof + solar", "email_body": "Hi Karen, ..."})
        self.client.post("/leads/3/email/reject")
        self.assertEqual(db.get_lead(self.db_path, 1)["email_status"], "Approved")
        self.assertEqual(db.get_lead(self.db_path, 2)["email_edited"], 1)
        self.assertEqual(db.get_lead(self.db_path, 3)["email_status"], "Rejected")
        for status in ["Contacted", "Qualified", "Closed"]:
            self.client.post("/leads/1/decisions", data={"status": status, "priority": "", "next_action": ""})
        stats = db.get_stats(self.db_path)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["high_priority"], 0)  # the only High lead is now Closed
        self.assertEqual(stats["drafts_pending"], 1)  # only the edited draft

    def test_incomplete_submissions(self):
        base = SCENARIOS[3]["form"]
        cases = {
            "no way to contact": (dict(base, phone=""), "Provide an email or a phone number"),
            "bad email": (dict(base, email="sam@"), "look valid"),
            "bad phone": (dict(base, phone="12"), "7 to 15 digits"),
            "no service": (dict(base, service_interest=""), "Please choose a service"),
            "blank names": (dict(base, first_name="  ", last_name=""), "First name is required"),
        }
        for label, (form, message) in cases.items():
            with self.subTest(label):
                resp = self.client.post("/leads", data=form)
                self.assertEqual(resp.status_code, 422)
                self.assertIn(message, resp.get_data(as_text=True))
        self.assertEqual(db.get_stats(self.db_path)["total"], 0)
        # Bare minimum: name, one contact method, service
        resp = self.client.post("/leads", data={"first_name": "Sam", "last_name": "Patel",
                                                "phone": "5125550199", "service_interest": "Unsure"})
        self.assertEqual(resp.status_code, 302)


class ScenarioLiveModeTests(ScenarioTests):
    """Same scenarios with a live AI that *underrates* every lead as Low.
    The deterministic rules must still protect the business priority floor."""
    demo_mode = False

    def test_scenarios_in_demo_mode(self):
        pass  # replaced below

    def test_rules_protect_priority_when_ai_underrates(self):
        def lazy_ai(system, user, config):
            return json.dumps({
                "summary": "A lead.", "intent": "Unknown", "priority": "Low", "department": "Solar Sales",
                "next_action": "Follow up.", "key_details": [], "missing_info": ["Phone number"],
                "followup_timeframe": "Whenever", "email_subject": "Hi", "email_body": "Hi there",
            })
        expected_floor = {"1": "High", "2": "Medium", "3": "Low", "4": "Low", "5": "Low"}
        with mock.patch.object(ai_client, "_call_llm", side_effect=lazy_ai):
            for s in SCENARIOS:
                with self.subTest(s["name"]):
                    lead, _ = self.run_scenario(s)
                    self.assertEqual(lead["source"], "llm")
                    self.assertEqual(lead["priority"], expected_floor[s["name"][0]])
                    # Combined projects are always routed to the combined team
                    if s["form"]["service_interest"] == "Solar + Roofing":
                        self.assertEqual(lead["department"], "Solar & Roofing Projects")
                    # AI said "Phone number" is missing: form-field checks belong to the rules
                    self.assertNotIn("Phone number", lead["missing_info"])

    def test_scenario_review_actions(self):
        pass

    def test_incomplete_submissions(self):
        pass


if __name__ == "__main__":
    unittest.main()
