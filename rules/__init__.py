"""Layer 1: deterministic software. No AI.

Anything with business consequences is decided here, in plain, testable Python:
input validation, required fields, routing, final priority, tags, warnings and
dates. The same input always gives the same result, and every decision
records a human-readable reason.
"""
