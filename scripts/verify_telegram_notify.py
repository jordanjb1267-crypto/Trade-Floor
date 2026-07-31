#!/usr/bin/env python3
"""Superseded forwarding stub.

`docs/audits/2026-07-31-telegram-notify-e2e.md` instructs the operator to
re-run this script on the trading laptop. The two parallel Telegram
implementations were consolidated on 2026-07-31 and the canonical verifier is
now `scripts/verify_telegram.py`, which runs the same getMe/sendMessage stages
plus the §19 command-surface assertions. This stub exists so the audit's
instruction keeps working; it adds nothing.
"""

import runpy
import sys
from pathlib import Path

sys.argv[0] = str(Path(__file__).with_name("verify_telegram.py"))
runpy.run_path(sys.argv[0], run_name="__main__")
