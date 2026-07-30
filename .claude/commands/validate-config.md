---
description: Validate all firm configuration files against the constitutional schema
---

Validate the firm's configuration:

1. Run `python3 scripts/validate_config.py` from the repository root.
2. If validation fails, report the exact violated invariant and its spec
   citation — do NOT weaken a validator to make a config load; the schema
   intentionally rejects constitution violations (§3.4).
3. If validation passes, confirm: environment, live_allowed status (must be
   empty outside live), risk-ladder/anchor consistency, and session anchoring
   (Europe/London).
4. Run `pytest tests/unit/test_config.py -q` and report the result.
