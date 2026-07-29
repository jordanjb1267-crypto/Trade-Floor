#!/usr/bin/env python3
"""Validate all firm configuration layers against the constitutional schema.

Usage: python3 scripts/validate_config.py
Exit 0 = all present layers valid; exit 1 = any violation (printed).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import ValidationError  # noqa: E402

from trading_firm.config import load_config  # noqa: E402

CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"


def main() -> int:
    failures = 0
    found = sorted(CONFIG_ROOT.glob("*/firm.yaml"))
    if not found:
        print("FAIL: no config layers found under config/*/firm.yaml")
        return 1
    for path in found:
        layer = path.parent.name
        try:
            cfg = load_config(path)
        except (ValidationError, Exception) as err:  # noqa: BLE001
            print(f"FAIL  config/{layer}/firm.yaml\n{err}\n")
            failures += 1
            continue
        live = "EMPTY" if not cfg.strategies.live_allowed else cfg.strategies.live_allowed
        print(
            f"OK    config/{layer}/firm.yaml  env={cfg.firm.environment}  "
            f"anchor=${cfg.risk.tier_anchor_usd:.0f}  live_allowed={live}  "
            f"session={cfg.session.activation_london}-{cfg.session.flatten_london} London"
        )
    print(f"\n{len(found) - failures}/{len(found)} layers valid")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
