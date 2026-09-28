"""Layer 3: decisions only a person can make.

  - approving, editing or rejecting customer-facing email (never auto-sent)
  - overriding the priority the rules decided
  - changing the AI's recommended next action
  - moving a lead through its statuses

Human input is still validated by deterministic code, and a priority override
re-runs the rules' follow-up date calculation.
"""
