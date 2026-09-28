"""Load realistic sample leads for demos.

    python seed.py          # add sample leads
    python seed.py --reset  # wipe the database first

Seeding always uses the deterministic demo AI, so it never calls the API.
"""
import sys
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import database as db
from config import Config
from pipeline import process_lead

# (days_ago, status, email_status, lead)
SAMPLES = [
    (0, "New", "Pending review", dict(
        first_name="Maria", last_name="Delgado", email="maria.delgado@example.com", phone="(512) 555-0147",
        address="4821 Juniper Ridge Dr, Austin, TX 78745", monthly_bill=410.0, service_interest="Solar + Roofing",
        message="Our roof is about 18 years old and we'd like to replace it before adding solar. Bills are brutal "
                "in summer and we just bought an EV. We own the home and want to get started this month if the "
                "numbers make sense. Is financing available?")),
    (0, "New", "Pending review", dict(
        first_name="Derek", last_name="Owens", email="", phone="(737) 555-0192", address="",
        monthly_bill=None, service_interest="Roofing",
        message="Water is leaking into the upstairs bedroom after last night's storm. Need someone out ASAP.")),
    # Demo moment: the AI reads "just curious" as Low; a business rule raises it to High.
    (0, "New", "Pending review", dict(
        first_name="Grace", last_name="Kim", email="grace.kim@example.com", phone="(512) 555-0131",
        address="2604 Hillcrest Ave, Austin, TX 78703", monthly_bill=480.0, service_interest="Solar",
        message="Just curious what solar might cost for a house our size. We own the home. No rush.")),
    (1, "Reviewed", "Approved", dict(
        first_name="Priya", last_name="Nair", email="priya.nair@example.com", phone="",
        address="77 Cedar Hollow Ln, Round Rock, TX 78664", monthly_bill=145.0, service_interest="Solar",
        message="Just researching for now. Curious about the tax credit and whether our trees would be a problem.")),
    (3, "New", "Pending review", dict(
        first_name="Tom", last_name="Brennan", email="tbrennan@example.com", phone="(512) 555-0110",
        address="1502 Wildflower Ct, Cedar Park, TX 78613", monthly_bill=265.0, service_interest="Unsure",
        message="We own our home and keep losing power in storms. Wondering if a battery backup or solar makes "
                "more sense for us. We're in an HOA.")),
    (5, "Contacted", "Approved", dict(
        first_name="Aisha", last_name="Karimi", email="aisha.karimi@example.com", phone="(512) 555-0168",
        address="9 Lantana Loop, Austin, TX 78704", monthly_bill=220.0, service_interest="Roofing",
        message="Homeowner here. Roof is 22 years old with some missing shingles. Would like a quote and to "
                "know about financing.")),
    (9, "Qualified", "Approved", dict(
        first_name="Luis", last_name="Ortega", email="luis.ortega@example.com", phone="(737) 555-0133",
        address="3310 Mesa Verde Dr, Pflugerville, TX 78660", monthly_bill=380.0, service_interest="Solar",
        message="We own the house and the roof is only 3 years old. Ready to move forward with solar and want to "
                "schedule a site visit.")),
]


def main():
    config = SimpleNamespace(**{k: getattr(Config, k) for k in dir(Config) if k.isupper()})
    config.DEMO_MODE = True
    db.init_db(config.DATABASE_PATH)

    if "--reset" in sys.argv:
        with db.connect(config.DATABASE_PATH) as conn:
            conn.execute("DELETE FROM analyses")
            conn.execute("DELETE FROM leads")
            conn.execute("DELETE FROM sqlite_sequence")  # restart ids at 1
        print("Cleared existing leads.")

    for days_ago, status, email_status, lead in SAMPLES:
        received = date.today() - timedelta(days=days_ago)
        result = process_lead(lead, config, today=received)
        lead_id = result["lead_id"]
        stamp = datetime.combine(received, datetime.now().time()).isoformat(timespec="seconds")
        with db.connect(config.DATABASE_PATH) as conn:
            conn.execute("UPDATE leads SET created_at = ?, updated_at = ? WHERE id = ?", (stamp, stamp, lead_id))
            conn.execute("UPDATE analyses SET created_at = ? WHERE lead_id = ?", (stamp, lead_id))
        if email_status != "Pending review":
            db.set_email_status(config.DATABASE_PATH, lead_id, email_status)
        db.update_status(config.DATABASE_PATH, lead_id, status)
        print(f"  + {lead['first_name']} {lead['last_name']} ({lead['service_interest']})")

    print(f"Seeded {len(SAMPLES)} sample leads into {config.DATABASE_PATH}.")


if __name__ == "__main__":
    main()
