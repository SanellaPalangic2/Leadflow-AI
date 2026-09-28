"""DEMO_MODE: deterministic, realistic stand-in for the LLM.

It performs the same *language* tasks as the live model (intent, summary,
context details, clarifying questions, email draft) using keyword heuristics,
and returns a JSON *string* exactly like the live model would. That string then goes through the same parsing and validation as
real AI output, so the full pipeline is exercised even without an API key.
The same input always produces the same output.
"""
import json
import re

from rules.business import DEPARTMENT_BY_SERVICE, NEEDS_BILL, URGENT_WORDS, mentions

SERVICE_PHRASES = {
    "Solar": "a solar installation",
    "Roofing": "roofing work",
    "Solar + Roofing": "a combined roof replacement and solar installation",
    "Unsure": "exploring energy and roofing options",
}
LEAK_WORDS = ("leak", "leaks", "leaking", "leaked", "leaky", "dripping", "water damage")
# (whole-word phrases, detail for the rep, phrase for the customer email).
# Negated mentions ("no HOA") are ignored.
DETAIL_PATTERNS = [
    (LEAK_WORDS, "Reports an active roof leak", "the leak"),
    (("storm damage", "hail", "hail damage", "wind damage", "missing shingles", "last night's storm", "after the storm"),
     "Mentions storm or weather damage", "the storm damage"),
    (("battery", "backup", "outage", "outages", "power goes out", "losing power"),
     "Interested in battery backup for outages", "backup power options for outages"),
    (("ev", "evs", "electric vehicle", "tesla", "electric car"),
     "Has or plans to buy an EV (higher usage)", "charging your EV"),
    (("hoa",), "Home is in an HOA; approval may be required", "your HOA's approval process"),
    (("tax credit", "tax credits", "incentive", "incentives", "rebate", "rebates"),
     "Asking about tax credits and incentives", "the tax credit and other incentives"),
    (("financing", "finance", "loan", "lease", "monthly payment"),
     "Interested in financing options", "financing options"),
    (("shade", "shading", "trees"), "Possible shading from trees", "how the trees might affect solar"),
    (("selling", "sell the house", "moving out"), "May be selling the home soon", "your plans for the home"),
    (("insurance", "claim"), "Insurance claim may be involved", "the insurance side"),
    (("hot", "drafty", "insulation", "attic"),
     "Mentions comfort issues (hot or drafty rooms)", "why some rooms are uncomfortable"),
]
READY_WORDS = ("asap", "as soon as possible", "this month", "this week", "ready to", "want to start",
               "get started", "sign", "schedule")
BROWSING_WORDS = ("just curious", "curious", "researching", "looking into", "not sure yet", "just exploring",
                  "next year", "just wondering", "general information", "some information")
OWNER_WORDS = ("own", "owns", "homeowner", "homeowners", "owner", "we bought", "i bought")
RENTER_WORDS = ("rent", "renting", "renter", "tenant", "landlord")
ROOF_AGE_PATTERNS = (
    re.compile(r"\broof\b[^.!?]*?\b(\d{1,2})[\s-]*(?:years?|yrs?)[\s-]*old"),   # "roof is 18 years old"
    re.compile(r"\b(\d{1,2})[\s-]*(?:year|yr)[\s-]*old\s+roof\b"),             # "18-year-old roof"
    re.compile(r"\broof\b[^.!?]*?\b(?:replaced|installed|put on)\b[^.!?]*?\b(\d{1,2})\s*(?:years?|yrs?)\s*ago"),
)


def generate_raw_response(lead: dict, config) -> str:
    msg = (lead.get("message") or "").lower()
    service = lead["service_interest"]
    first = lead["first_name"]
    has = lambda words: mentions(msg, words)  # noqa: E731

    # --- intent + AI priority (the rules engine may still raise it) ---
    if has(URGENT_WORDS):
        intent, priority = "Urgent repair", "High"
    elif has(READY_WORDS):
        intent, priority = "Ready to move forward", "High"
    elif has(BROWSING_WORDS):
        intent, priority = "Researching options", "Low"
    elif service == "Unsure":
        intent, priority = "Unclear needs; discovery call", "Medium"
    else:
        intent, priority = "Requesting a quote", "Medium"

    # --- key details ---
    matched = [(detail, phrase) for words, detail, phrase in DETAIL_PATTERNS if has(words)]
    roof_age = next((m for p in ROOF_AGE_PATTERNS if (m := p.search(msg))), None)
    if roof_age:
        matched.insert(0, (f"Roof is about {roof_age.group(1)} years old", "the age and condition of your roof"))
    renter = has(RENTER_WORDS)
    if renter:
        matched.append(("May be renting; the property owner must approve", "getting the property owner's approval"))
    details = [detail for detail, _ in matched]
    email_topics = [phrase for _, phrase in matched]

    # --- questions the message raises (form-field checks belong to the rules) ---
    missing = []
    if len(msg.split()) < 6:
        missing.append("What they're hoping to achieve")
    if service in NEEDS_BILL and not roof_age:
        missing.append("Roof age and condition")
    if renter:
        missing.append("Property owner's contact and approval")
    elif not has(OWNER_WORDS):
        missing.append("Confirmation that they own the home")
    if "Reports an active roof leak" in details:
        missing.append("Photos of the affected area")

    # --- summary + next action ---
    bill = lead.get("monthly_bill")
    bill_part = f" with an electric bill of about ${bill:.0f}/month" if bill is not None else ""
    summary = f"{first} {lead['last_name']} is interested in {SERVICE_PHRASES[service]}{bill_part}."
    if details:
        summary += f" {details[0]}."

    if intent == "Urgent repair":
        next_action = "Call today to schedule an emergency roof inspection."
    elif intent == "Researching options":
        next_action = "Send an overview of costs, incentives and the process; offer a no-pressure call."
    elif service == "Solar + Roofing":
        next_action = "Book a site visit to assess the roof and quote a combined project."
    elif service == "Solar" and bill is None:
        next_action = "Request a recent utility bill and schedule a solar consultation."
    elif service == "Solar":
        next_action = "Schedule a solar consultation and site assessment."
    elif service == "Roofing":
        next_action = "Schedule a roof inspection and gather photos of the roof."
    else:
        next_action = "Call to understand their goals and recommend the right service."

    timeframe = {"High": "Within 24 hours", "Medium": "Within 3 business days", "Low": "Within 1 week"}[priority]

    # --- email draft ---
    detail_line = ""
    if email_topics and intent != "Urgent repair":
        topics = email_topics[:2]
        detail_line = f" We'll be sure to cover {' and '.join(topics)} when we talk."
    if intent == "Urgent repair":
        opener = "I'm sorry to hear about the trouble with your roof. We'd like to get someone out to take a look as quickly as possible."
    else:
        opener = f"Thank you for reaching out about {SERVICE_PHRASES[service]}. I'd be glad to help you figure out the best option for your home."
    ask = "Could you reply with a couple of times that work for a short call this week?"
    if intent == "Researching options":
        ask = ("I'll send over a short overview of how it works, what it costs and which incentives apply. "
               "Whenever you're ready, I'm happy to set up a no-pressure call.")
    elif service in NEEDS_BILL and bill is None:
        ask = "If you can, please reply with a recent electric bill, along with a couple of times that work for a short call."
    next_step = ("" if intent == "Researching options"
                 else "The next step is a quick conversation so we can understand your home and goals. ")
    body = (
        f"Hi {first},\n\n{opener}{detail_line}\n\n"
        f"{next_step}{ask}\n\n"
        f"There's no obligation, and I'm happy to answer any questions in the meantime.\n\n"
        f"Best regards,\n{config.SENDER_NAME}\n{config.COMPANY_NAME}"
    )
    if intent == "Urgent repair":
        subject = "Getting your roof looked at quickly"
    elif intent == "Researching options":
        subject = f"Answers to your {service.lower()} questions" if service != "Unsure" else "Answers to your questions"
    else:
        subject = {
            "Solar + Roofing": "Your roof and solar project: next steps",
            "Solar": "Next steps for your solar consultation",
            "Roofing": "Next steps for your roofing project",
            "Unsure": "Following up on your inquiry",
        }[service]

    # Department suggestion from the message (the rules only use it for "Unsure")
    if service != "Unsure":
        department = DEPARTMENT_BY_SERVICE[service]
    elif has(LEAK_WORDS) or has(("roof", "shingles", "storm damage", "hail")):
        department = "Roofing Services"
    elif has(("solar", "panels", "solar panels")):
        department = "Solar Sales"
    else:
        department = "Energy Consultation"

    return json.dumps(
        {
            "summary": summary,
            "intent": intent,
            "priority": priority,
            "department": department,
            "next_action": next_action,
            "key_details": details,
            "missing_info": missing,
            "followup_timeframe": timeframe,
            "email_subject": subject,
            "email_body": body,
        },
        indent=2,
    )
