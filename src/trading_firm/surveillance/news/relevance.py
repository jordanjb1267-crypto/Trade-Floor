"""Deterministic instrument-relevance prefilter (§30.3.H, §30.15).

The cheap, mechanical half of relevance: which registered instruments a
news item COULD touch, from currency mentions alone. The judgment half —
materiality, pricing assessment, recommended state — belongs to the News
Verification and Relevance Agent and arrives schema-validated. Keeping the
prefilter deterministic is a §30.15 cost control: items touching no traded
currency never spend an invocation.
"""

from __future__ import annotations

import re

# Currency vocabulary worth prefiltering for the current FX book. A miss here
# costs one agent invocation, never a trade — the prefilter only excludes.
_CURRENCY_HINTS: dict[str, frozenset[str]] = {
    "GBP": frozenset({"gbp", "sterling", "pound", "boe", "bank of england"}),
    "USD": frozenset({"usd", "dollar", "fed", "fomc", "federal reserve", "treasury"}),
    "EUR": frozenset({"eur", "euro", "ecb", "european central bank", "eurozone"}),
}


def mentioned_currencies(headline: str) -> frozenset[str]:
    text = " " + re.sub(r"[^\w\s]", " ", headline.casefold()) + " "
    found = set()
    for currency, hints in _CURRENCY_HINTS.items():
        if any(f" {hint} " in text or f" {hint}s " in text for hint in hints):
            found.add(currency)
    return frozenset(found)


def potentially_affected(
    headline: str, registered_instruments: tuple[str, ...]
) -> tuple[str, ...]:
    currencies = mentioned_currencies(headline)
    return tuple(
        instrument
        for instrument in registered_instruments
        if currencies & frozenset(instrument.split("_"))
    )
