"""Five realistic demo scenarios and what LeadFlow should do with each.

Used by tests/test_scenarios.py (automated) and handy for a live demo:
paste any of these into the New lead form.
"""

SCENARIOS = [
    {
        "name": "1. High-priority solar lead",
        "form": {
            "first_name": "Marcus", "last_name": "Webb", "email": "marcus.webb@example.com",
            "phone": "(512) 555-0182", "address": "2217 Bluebonnet Ln, Austin, TX 78704",
            "monthly_bill": "$465", "service_interest": "Solar",
            "message": "We own our home and the electric bill has been over $450 every month this summer. "
                       "The roof was replaced 4 years ago and faces south. We'd like to get started this "
                       "month. Can someone come out for a site visit?",
        },
        "expect": {
            "priority": "High", "department": "Solar Sales", "tags_include": ["High bill"],
            "warnings": [], "follow_up_business_days": 1, "monthly_bill": 465.0,
            "details_include": ["Roof is about 4 years old"], "details_exclude": ["EV"],
            "missing_exclude": ["Roof age", "own the home"],
        },
    },
    {
        "name": "2. Solar + roofing lead",
        "form": {
            "first_name": "Karen", "last_name": "Liu", "email": "karen.liu@example.com",
            "phone": "(737) 555-0124", "address": "905 Oak Meadow Dr, Round Rock, TX 78681",
            "monthly_bill": "about 240 a month", "service_interest": "Solar + Roofing",
            "message": "Our roof is about 20 years old and the shingles are starting to curl. If we're "
                       "replacing it anyway, we'd like to add solar at the same time. We're in an HOA. "
                       "What financing options do you have?",
        },
        "expect": {
            "priority": "Medium", "department": "Solar & Roofing Projects",
            "tags_include": ["Bundle opportunity"], "warnings": [], "follow_up_business_days": 3,
            "monthly_bill": 240.0,
            "details_include": ["Roof is about 20 years old", "Home is in an HOA; approval may be required",
                                "Interested in financing options"],
        },
    },
    {
        "name": "3. Low-priority information request",
        "form": {
            "first_name": "Ben", "last_name": "Foster", "email": "ben.foster@example.com",
            "phone": "(512) 555-0156", "address": "44 Sunfield Ct, Kyle, TX 78640",
            "monthly_bill": "95", "service_interest": "Solar",
            "message": "Just curious how solar works and whether the federal tax credit is still available. "
                       "Probably not doing anything until next year.",
        },
        "expect": {
            "priority": "Low", "department": "Solar Sales", "tags_exclude": ["Urgent", "High bill"],
            "warnings": [], "follow_up_business_days": 5, "intent": "Researching options",
            "details_include": ["Asking about tax credits and incentives"],
            "email_includes": "no-pressure",
        },
    },
    {
        "name": "4. Lead with missing information",
        "form": {
            "first_name": "Sam", "last_name": "Patel", "email": "", "phone": "(512) 555-0199",
            "address": "", "monthly_bill": "", "service_interest": "Solar",
            "message": "Call me about solar.",
        },
        "expect": {
            "priority": "Medium", "department": "Solar Sales", "follow_up_business_days": 3,
            "warnings_include": ["No email address", "No property address", "No electric bill"],
            # Empty form fields are flagged by the rules (warnings), not by the AI...
            "missing_exclude": ["Email", "Phone", "Address", "bill"],
            # ...while the AI raises questions only the message context can answer.
            "missing_include": ["What they're hoping to achieve", "Roof age and condition"],
        },
    },
    {
        "name": "5. Ambiguous customer inquiry",
        "form": {
            "first_name": "Alex", "last_name": "Moreno", "email": "alex.moreno@example.com",
            "phone": "(737) 555-0171", "address": "118 Pecan St, Georgetown, TX 78626",
            "monthly_bill": "", "service_interest": "Unsure",
            "message": "Saw one of your trucks in the neighborhood. Not sure what we need. Upstairs gets "
                       "really hot in the afternoon and our bills seem high. What do you guys actually do?",
        },
        "expect": {
            "priority": "Medium", "department": "Energy Consultation", "follow_up_business_days": 3,
            "intent": "Unclear needs; discovery call", "warnings_include": ["No electric bill"],
            "details_include": ["Mentions comfort issues (hot or drafty rooms)"],
            "tags_exclude": ["Urgent", "Bundle opportunity"],
        },
    },
]
