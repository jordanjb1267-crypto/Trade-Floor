"""Global Market Intelligence and Surveillance Division (§30).

Deterministic surveillance services: Market State Objects, source and
feature governance, event and alert discipline, post-entry monitoring —
everything behind `surveillance.enabled: false` until the §30.18 phases
say otherwise. Nothing in this package can reach an order path, raise a
risk tier, or alter a classification input (§30.2, §5.1).

Modules import lazily where it matters; importing the package has no side
effects beyond defining names.
"""
