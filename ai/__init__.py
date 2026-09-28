"""Layer 2: language tasks for the LLM.

The AI is used only where free text has to be understood or written:
  - understanding the customer's intent and urgency from their message
  - summarizing the inquiry
  - picking out contextual details (roof age, HOA, EV, financing, ...)
  - raising questions only the message context can reveal
  - drafting a personalized follow-up email

Its priority, department and timing are *suggestions*. The rules layer makes
the actual decisions, and the human layer approves anything customer-facing.
AI output is untrusted input: ai/schema.py validates it before use.
"""
