# LeadFlow

An AI-assisted sales lead intake prototype for a solar and roofing company. LeadFlow turns a manual
process (read the inquiry, judge urgency, route it, write a reply, schedule a follow-up) into an
automated workflow that still keeps a person in control.

**Design principle: AI suggests, rules decide, people approve.**

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # Windows: copy .env.example .env
python seed.py --reset                                 # optional: load 6 sample leads
flask run                                              # open http://127.0.0.1:5001
```

The app runs on port **5001** because macOS reserves port 5000 for AirPlay. Keep Flask debug mode off
for demos, since debug mode shows stack traces in the browser.

Run the tests with `python -m unittest discover tests -v`. `tests/scenarios.py` has five realistic
leads (high-priority solar, solar + roofing, an information request, missing information, and an
ambiguous inquiry) that you can also paste into the form during a demo.

### Pre-demo checklist

1. Start the app and check the terminal line `LeadFlow starting: DEMO_MODE=...`.
2. Check the header badge: **Demo mode**, **Live AI**, or a red **No API key** warning.
3. For a clean dashboard, run `python seed.py --reset` (or delete `leadflow.db`).

### Live AI mode

In `.env`, set `DEMO_MODE=false` and `ANTHROPIC_API_KEY=...`, then restart the app. The header badge
switches from **Demo mode** to **Live AI**. If the API is down, the key is wrong, or the model returns
bad JSON, the lead is still saved using a rule-based fallback and flagged for manual review.

## Deploy on Render (free) with the real AI

1. Push this folder to a GitHub repository (`.env` and `leadflow.db` are git-ignored, so no secrets are uploaded).
2. On [render.com](https://render.com), choose **New → Blueprint** and pick the repository. `render.yaml` configures everything.
3. In Render, open the **leadflow** service → **Environment** and add two secrets:
   - `ANTHROPIC_API_KEY`: your Claude API key
   - `APP_PASSWORD`: the password visitors must enter
4. Save; Render redeploys. Open the `https://leadflow-xxxx.onrender.com` link and sign in.

Safeguards for a public site:
- **Password page** in front of every page (only `/healthz`, used by Render's health check, is open).
- **Hourly AI limit** (`AI_HOURLY_LIMIT`, default 30). Past it, leads still save using rule-based defaults.
- Secrets live only in Render's settings, never in GitHub.
- Sample leads are rebuilt on every restart using the built-in demo analysis, so restarts cost nothing.
- Also put only a small prepaid credit on your Claude account, with automatic top-ups off, as a hard spending cap.

On the free plan the site sleeps after ~15 minutes idle; the first visit then takes ~1 minute.

## Architecture: who decides what

AI is used only where it adds value: understanding and writing language. Anything with
business consequences is plain Python, and anything customer-facing needs a person.

| Layer | Folder | Decides | Why this layer |
|---|---|---|---|
| **Rule** (deterministic software) | `rules/` | Input validation, required fields, final priority, routing, tags, missing-field warnings, follow-up dates | Must be predictable, testable, auditable and identical every time |
| **AI** (LLM) | `ai/` | Customer intent and urgency from free text, summary, context details (roof age, HOA, EV…), clarifying questions, personalized email draft | Needs to understand messy human language, which rules can't do well |
| **Human** | `human/` | Approve / edit / reject emails, override priority, change the next action, move lead status | Customer-facing and judgment calls need accountability |

How the layers interact:

- The AI's priority, department and timing are **suggestions**. The rules can raise the AI's urgency
  (e.g. bill ≥ $350 → High) but never lower it. Known services use a fixed routing table, and only an
  "Unsure" lead uses the AI's reading of the message, restricted to the approved department list.
  The AI's suggested timing is shown but never sets the date.
- Whether a form field is empty is a fact, so the rules check it and any AI claims about it are dropped.
- A person's priority override wins, and the rules then recalculate the follow-up date.
- The database stores all three side by side (`ai_priority`, `rule_priority`, `human_priority`;
  `ai_next_action`, `human_next_action`), so the **Why this decision?** panel on each lead can show
  who decided what, and why.
- `tests/test_layers.py` enforces the boundaries: `rules/` can't import the AI, the database or
  HTTP libraries, and `ai/` can't save data or make human decisions.

```
Browser form ─► app.py (routes only)
                  │
                  ├─ rules/validation.py   RULE   required fields, formats
                  ▼
               pipeline.py
                  ├─ ai/client.py | ai/demo.py   AI     read the message, draft the email
                  ├─ ai/schema.py                RULE   validate AI output (untrusted input)
                  ├─ rules/business.py           RULE   priority, routing, warnings, dates
                  └─ database.py                        save lead + AI output + decisions
                  ▼
               Lead page ─► human/review.py      HUMAN  approve email, override, next action
                  └─ explain.py                         "Why this decision?" panel
```

| File | Responsibility |
|---|---|
| `app.py` | Flask routes, CSRF check, friendly error pages |
| `pipeline.py` | Runs the workflow: AI interpretation, then rule decisions, then save |
| `rules/validation.py` | Required fields, email/phone format, bill parsing |
| `rules/business.py` | Priority floors, routing, tags, warnings, follow-up dates, all with reasons |
| `rules/fallback.py` | Safe defaults when the AI is unavailable |
| `ai/client.py` | Prompt + LLM call (Anthropic Messages API); maps API errors to safe messages |
| `ai/demo.py` | Deterministic stand-in for the LLM (DEMO_MODE) |
| `ai/schema.py` | Parses and validates AI JSON against the rules' allowed values |
| `human/review.py` | Email approval, priority override, next-action changes, status |
| `explain.py` | Builds the "Why this decision?" rows from stored AI / rule / human values |
| `database.py` | Schema, queries, automatic upgrade of older databases |
| `seed.py` | Loads sample leads for demos |

### Business rules (`rules/business.py`)

- Bill ≥ $350/month → **High**, tagged *High bill*. Bill ≥ $200 → at least **Medium**.
- Message mentions a leak, storm damage or an emergency repair → **High**, tagged *Urgent*.
  This is a keyword safety net, even if the AI misses it.
- Solar + Roofing → at least **Medium**, tagged *Bundle opportunity*, routed to *Solar & Roofing Projects*.
- Missing email, phone, address, or (for solar) bill → visible warnings.
- Follow-up date: High = 1 business day, Medium = 3, Low = 5 (weekends skipped).

### Reliability and security

- API keys only come from `.env`, which is git-ignored. They are never logged or rendered. At startup the
  app logs only *whether* a key is present.
- AI output is parsed defensively (it tolerates code fences and extra prose) and then schema-validated.
  Unexpected values are dropped, and any AI claims about form fields (e.g. "phone number missing")
  are removed, because the rules check those.
- Any AI failure falls back to rule-based analysis, so no lead is lost. This covers timeouts, a bad key,
  a wrong model name, a cut-off response, invalid JSON and unexpected exceptions. Temporary API overloads
  are retried once.
- The lead's message is wrapped as data in the prompt. The model is told not to follow instructions
  inside it, and customer text can't close the data block.
- Keyword rules match whole words and ignore negations, so "no leaks" isn't urgent and "every" isn't "EV".
- Flask debug mode is off. 400/404/405/413/500 errors show friendly pages with no stack traces. If saving
  fails, or the session expires (e.g. after a server restart), the form comes back with the user's input intact.
- Every POST requires a CSRF token. The session cookie is HttpOnly and SameSite=Lax, request size is capped,
  and SQL uses parameterized queries.
- Emails are never sent automatically. Approval status and timestamp are stored.
