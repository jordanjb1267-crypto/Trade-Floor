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
from trading_firm.surveillance.config import load_surveillance_config  # noqa: E402

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

    # Surveillance layers (§30.12) have their own schema and loader; a layer
    # without the file simply has no surveillance, which is a valid state —
    # but a file that exists and fails to validate fails the run.
    for path in sorted(CONFIG_ROOT.glob("*/surveillance.yaml")):
        layer = path.parent.name
        try:
            sur = load_surveillance_config(path)
        except (ValidationError, Exception) as err:  # noqa: BLE001
            print(f"FAIL  config/{layer}/surveillance.yaml\n{err}\n")
            failures += 1
            continue
        print(
            f"OK    config/{layer}/surveillance.yaml  enabled={sur.enabled}  "
            f"mode={sur.mode}  influence="
            f"{sur.influence_candidate_generation or sur.influence_live_eligibility}  "
            f"phone>={sur.alerts.telegram_minimum_severity}"
        )

    print(f"\n{len(found) - failures}/{len(found)} firm layers valid")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
