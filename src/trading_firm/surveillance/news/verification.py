"""News verification state machine (§30.3.H).

Deterministic transitions over the seven controlled states. Corroboration
requires INDEPENDENT sources — the same source repeating itself is still
SINGLE_SOURCE — and a conflict, correction, or retraction can only tighten,
never quietly relax: the machine refuses transitions that would move a
RETRACTED item back to verified without a new item superseding it.
"""

from __future__ import annotations

from trading_firm.surveillance.schemas import VerificationState

# States that may never be LEFT except via supersession by a new item.
_TERMINAL = frozenset({VerificationState.RETRACTED})

# The only legal transitions; everything else raises.
_LEGAL: dict[VerificationState, frozenset[VerificationState]] = {
    VerificationState.UNVERIFIED: frozenset(
        {
            VerificationState.SINGLE_SOURCE,
            VerificationState.CORROBORATED,
            VerificationState.OFFICIAL_SOURCE,
            VerificationState.CONFLICTING,
        }
    ),
    VerificationState.SINGLE_SOURCE: frozenset(
        {
            VerificationState.CORROBORATED,
            VerificationState.OFFICIAL_SOURCE,
            VerificationState.CONFLICTING,
            VerificationState.CORRECTED,
            VerificationState.RETRACTED,
        }
    ),
    VerificationState.CORROBORATED: frozenset(
        {
            VerificationState.OFFICIAL_SOURCE,
            VerificationState.CONFLICTING,
            VerificationState.CORRECTED,
            VerificationState.RETRACTED,
        }
    ),
    VerificationState.OFFICIAL_SOURCE: frozenset(
        {
            VerificationState.CONFLICTING,
            VerificationState.CORRECTED,
            VerificationState.RETRACTED,
        }
    ),
    VerificationState.CONFLICTING: frozenset(
        {
            VerificationState.CORROBORATED,
            VerificationState.OFFICIAL_SOURCE,
            VerificationState.CORRECTED,
            VerificationState.RETRACTED,
        }
    ),
    VerificationState.CORRECTED: frozenset(
        {
            VerificationState.CORROBORATED,
            VerificationState.OFFICIAL_SOURCE,
            VerificationState.CONFLICTING,
            VerificationState.RETRACTED,
        }
    ),
    VerificationState.RETRACTED: frozenset(),
}


def transition(
    current: VerificationState, target: VerificationState
) -> VerificationState:
    if target is current:
        return current
    if target not in _LEGAL[current]:
        raise ValueError(
            f"illegal verification transition {current} -> {target}: a retracted "
            f"or conflicted item does not quietly become trustworthy again "
            f"(§30.3, §30.8) — a new superseding item starts at UNVERIFIED"
        )
    return target


def state_for_sources(
    independent_source_ids: frozenset[str],
    official_source_ids: frozenset[str],
) -> VerificationState:
    """Initial verification from attribution alone. Independence means
    distinct registered sources, not distinct URLs at one provider."""
    if independent_source_ids & official_source_ids:
        return VerificationState.OFFICIAL_SOURCE
    if len(independent_source_ids) >= 2:
        return VerificationState.CORROBORATED
    if len(independent_source_ids) == 1:
        return VerificationState.SINGLE_SOURCE
    return VerificationState.UNVERIFIED
