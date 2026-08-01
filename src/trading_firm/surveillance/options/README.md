# Options-ready boundaries — documentation only (§30.11)

By owner decision (2026-07-31) the options scaffold is prose, not code:
OANDA US is a spot-FX RFED and cannot trade options (D-1, §30.11), so empty
importable modules here would be dead code with an authority problem. This
README is the reserved boundary.

Reserved module boundaries, documented and inactive: underlying state,
implied volatility, volatility surface, greeks, chain liquidity, event
catalysts, contract selection, expiration and assignment.

Future options agents, documented and inactive (§30.11): Underlying
Technical Analyst, Implied Volatility Analyst, Greeks and Convexity
Monitor, Options Chain and Liquidity Monitor, Options Flow Analyst,
Corporate Event and Catalyst Monitor, Contract Selection Agent, Exercise
Assignment and Expiration Monitor, Options Portfolio Risk Officer.

What keeps the division options-ready today is not stubs but neutrality:
surveillance interfaces carry `instrument_id`, `asset_class`, `venue`, and
friends, and no pip semantics are hard-coded into the domain (§30.11,
tested by the asset-class-neutral rows in §30.17).

A separate owner-approved options amendment must define data vendors,
broker permissions, risk limits, supported structures, suitability
controls, and testing requirements before any module exists under this
directory. `options_scaffold.enabled` and `.registered` are false and the
config loader refuses true (§30.12).
