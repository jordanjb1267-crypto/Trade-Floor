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
    checked = 0
    found = sorted(CONFIG_ROOT.glob("*/firm.yaml"))
    if not found:
        print("FAIL: no config layers found under config/*/firm.yaml")
        return 1
    for path in found:
        layer = path.parent.name
        checked += 1
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
        checked += 1
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

    # Registries (§30.7, §30.8): versioned files with their own loaders.
    from trading_firm.features.registry import load_feature_registry  # noqa: E402
    from trading_firm.surveillance.sources.registry import (  # noqa: E402
        load_context_instruments,
        load_source_registry,
    )

    for label, loader, summarize in (
        (
            "config/registries/sources.yaml",
            load_source_registry,
            lambda reg: f"sources={len(reg.sources)}  "
            f"production_approved={sum(r.production_approved for r in reg.sources)}",
        ),
        (
            "config/registries/features.yaml",
            load_feature_registry,
            lambda reg: f"features={len(reg.features)}  "
            f"production={sum(r.status == 'production' for r in reg.features)}",
        ),
        (
            "config/registries/market_context_instruments.yaml",
            load_context_instruments,
            lambda instruments: f"context_instruments={list(instruments) or 'EMPTY'}",
        ),
    ):
        path = CONFIG_ROOT.parent / label
        checked += 1
        if not path.exists():
            print(f"FAIL  {label}: missing")
            failures += 1
            continue
        try:
            loaded = loader(path)
        except (ValidationError, Exception) as err:  # noqa: BLE001
            print(f"FAIL  {label}\n{err}\n")
            failures += 1
            continue
        print(f"OK    {label}  {summarize(loaded)}")

    print(f"\n{checked - failures}/{checked} configuration artifacts valid")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
