"""External intelligence source governance (§30.8).

The registry is the only place a source may be declared; adapters refuse
ids the registry does not carry. Nothing here polls anything — adapters
normalize data handed to them, and live polling arrives with its rollout
phase, not with this package.
"""
