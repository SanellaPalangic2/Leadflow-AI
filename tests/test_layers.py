"""Tests for the Rule / AI / Human separation.

    python -m unittest tests.test_layers -v
"""
import ast
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ai.client as ai_client  # noqa: E402
import database as db  # noqa: E402
from app import create_app  # noqa: E402
from explain import explain  # noqa: E402
from rules.business import add_business_days  # noqa: E402

LEAD = {"first_name": "Karen", "last_name": "Liu", "email": "k@example.com", "phone": "5125550124",
        "address": "905 Oak Meadow Dr", "monthly_bill": "240", "service_interest": "Solar + Roofing",
        "message": "Roof is 20 years old. We're in an HOA. What financing do you have?"}


def ai_json(**overrides):
    data = {"summary": "S", "intent": "I", "priority": "Low", "department": "Roofing Services",
            "next_action": "AI action.", "key_details": [], "missing_info": [],
            "followup_timeframe": "Within 2 weeks", "email_subject": "Hi", "email_body": "Hi there"}
    data.update(overrides)
    return json.dumps(data)


class LayerTestCase(unittest.TestCase):
    demo = True

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.client = create_app({"DATABASE_PATH": self.db_path, "DEMO_MODE": self.demo, "CSRF_DISABLED": True,
                                  "SECRET_KEY": "t", "ANTHROPIC_API_KEY": "sk-test"}).test_client()

    def tearDown(self):
        os.remove(self.db_path)

    def lead(self, lead_id=1):
        return db.get_lead(self.db_path, lead_id)

    def row(self, label, lead_id=1):
        return next(r for r in explain(self.lead(lead_id)) if r["label"] == label)


class HumanOverrideTests(LayerTestCase):
    def decide(self, status="New", priority="", next_action=""):
        return self.client.post("/leads/1/decisions", follow_redirects=True,
                                data={"status": status, "priority": priority, "next_action": next_action})

    def test_priority_override_recalculates_follow_up_date(self):
        self.client.post("/leads", data=LEAD)
        before = self.lead()
        self.assertEqual((before["rule_priority"], before["priority"]), ("Medium", "Medium"))
        received = date.fromisoformat(before["created_at"][:10])

        page = self.decide(priority="High").get_data(as_text=True)
        after = self.lead()
        self.assertEqual((after["priority"], after["human_priority"], after["rule_priority"]), ("High", "High", "Medium"))
        self.assertEqual(after["follow_up_date"], add_business_days(received, 1).isoformat())
        self.assertIn("priority set to High by you", page)
        self.assertIn("follow-up date recalculated", page)
        self.assertEqual(db.get_stats(self.db_path)["high_priority"], 1)
        self.assertEqual(self.row("Priority")["sources"], ["Human"])
        self.assertIn("rules had decided Medium", self.row("Priority")["reason"])
        self.assertIn(">manual<", self.client.get("/").get_data(as_text=True))

        self.decide(priority="")  # hand the decision back to the rules
        restored = self.lead()
        self.assertIsNone(restored["human_priority"])
        self.assertEqual(restored["follow_up_date"], before["follow_up_date"])

    def test_override_equal_to_rules_is_not_stored(self):
        self.client.post("/leads", data=LEAD)
        page = self.decide(priority="Medium").get_data(as_text=True)
        self.assertIsNone(self.lead()["human_priority"])
        self.assertIn("No changes", page)

    def test_next_action_change_and_reset(self):
        self.client.post("/leads", data=LEAD)
        ai_action = self.lead()["ai_next_action"]
        self.decide(next_action="Call Karen Tuesday about HOA paperwork.")
        lead = self.lead()
        self.assertEqual(lead["next_action"], "Call Karen Tuesday about HOA paperwork.")
        self.assertEqual(lead["ai_next_action"], ai_action)  # the AI's suggestion is kept for the record
        self.assertEqual(self.row("Next action")["sources"], ["Human"])
        self.assertIn(ai_action, self.row("Next action")["reason"])

        self.decide(next_action="")  # cleared -> back to the AI's suggestion
        self.assertEqual(self.lead()["next_action"], ai_action)
        self.assertEqual(self.row("Next action")["sources"], ["AI"])

    def test_invalid_human_input_is_rejected(self):
        self.client.post("/leads", data=LEAD)
        page = self.decide(priority="URGENT").get_data(as_text=True)
        self.assertIn("Unknown priority", page)
        self.assertIsNone(self.lead()["human_priority"])
        page = self.decide(next_action="x" * 301).get_data(as_text=True)
        self.assertIn("under 300 characters", page)


class DecisionSourceTests(LayerTestCase):
    def test_why_panel_explains_each_decision(self):
        self.client.post("/leads", data=dict(LEAD, monthly_bill="465", service_interest="Solar",
                                             message="Just curious about solar for next year."))
        rows = {r["label"]: r for r in explain(self.lead())}
        self.assertEqual(rows["Priority"]["sources"], ["Rule"])
        self.assertIn("The AI read the message as Low; raised because: Monthly bill of $465", rows["Priority"]["reason"])
        self.assertEqual(rows["Department"]["sources"], ["Rule"])
        self.assertIn("Solar leads always route to Solar Sales", rows["Department"]["reason"])
        self.assertIn("High priority → 1 business day", rows["Follow-up date"]["reason"])
        self.assertIn("(not used)", rows["Follow-up date"]["reason"])
        self.assertNotIn("Missing fields", rows)  # nothing missing, so no row
        self.assertEqual(rows["Summary & details"]["sources"], ["AI"])
        self.assertEqual(rows["Email"]["sources"], ["AI", "Human"])
        page = self.client.get("/leads/1").get_data(as_text=True)
        self.assertIn("Why this decision?", page)
        self.assertIn("Your decisions", page)


class RoutingTests(LayerTestCase):
    demo = False

    def test_known_service_ignores_ai_department(self):
        with mock.patch.object(ai_client, "_call_llm", return_value=ai_json(department="Roofing Services")):
            self.client.post("/leads", data=dict(LEAD, service_interest="Solar"))
        self.assertEqual(self.lead()["department"], "Solar Sales")
        self.assertEqual(self.lead()["ai_department"], "Roofing Services")  # kept for the record
        self.assertEqual(self.row("Department")["sources"], ["Rule"])

    def test_unsure_service_uses_ai_reading_of_the_message(self):
        with mock.patch.object(ai_client, "_call_llm", return_value=ai_json(department="Roofing Services")):
            self.client.post("/leads", data=dict(LEAD, service_interest="Unsure"))
        self.assertEqual(self.lead()["department"], "Roofing Services")
        self.assertEqual(self.row("Department")["sources"], ["AI"])

    def test_unsure_with_invalid_ai_department_falls_back_to_rule(self):
        with mock.patch.object(ai_client, "_call_llm", return_value=ai_json(department="Marketing")):
            self.client.post("/leads", data=dict(LEAD, service_interest="Unsure"))
        self.assertEqual(self.lead()["department"], "Energy Consultation")
        self.assertEqual(self.row("Department")["sources"], ["Rule"])

    def test_ai_timeframe_never_sets_the_date(self):
        with mock.patch.object(ai_client, "_call_llm", return_value=ai_json(followup_timeframe="Within 2 weeks")):
            self.client.post("/leads", data=LEAD)
        received = date.fromisoformat(self.lead()["created_at"][:10])
        self.assertEqual(self.lead()["follow_up_date"], add_business_days(received, 3).isoformat())  # Medium rule


class MigrationTests(unittest.TestCase):
    def test_database_from_previous_version_is_upgraded(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "old.db")
        shutil.copy(ROOT / "tests" / "fixtures" / "leadflow_v1.db", path)
        client = create_app({"DATABASE_PATH": path, "DEMO_MODE": True, "CSRF_DISABLED": True,
                             "SECRET_KEY": "t"}).test_client()
        lead = db.get_lead(path, 1)
        self.assertIn(lead["rule_priority"], ("Low", "Medium", "High"))
        self.assertEqual(lead["priority"], lead["rule_priority"])
        self.assertTrue(lead["next_action"])
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/leads/1").status_code, 200)
        client.post("/leads/1/decisions", data={"status": "Contacted", "priority": "Low", "next_action": ""})
        self.assertEqual(db.get_lead(path, 1)["priority"], "Low")
        shutil.rmtree(tmp)


class ArchitectureTests(unittest.TestCase):
    """The layer boundaries are enforced, not just documented."""
    FORBIDDEN = {
        "rules": {"ai", "human", "database", "flask", "requests"},  # pure decisions: no AI, no I/O
        "ai": {"human", "database", "flask"},                       # language only: can't approve or save
    }

    def imports_of(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_layer_dependencies(self):
        for package, forbidden in self.FORBIDDEN.items():
            for path in (ROOT / package).glob("*.py"):
                with self.subTest(str(path.relative_to(ROOT))):
                    self.assertFalse(self.imports_of(path) & forbidden)

    def test_ai_output_never_reaches_the_database_unvalidated(self):
        source = (ROOT / "pipeline.py").read_text()
        self.assertIn("validate_analysis(parse_json_text(raw))", source)


if __name__ == "__main__":
    unittest.main()
