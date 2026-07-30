# Incident Policy

Kill-switch behavior, escalation, and incident recording (§8.1, §18, §19).

## Kill-switch triggers and emergency policy (§8.1)

| Trigger | Live-position action |
|---|---|
| Manual owner activation | Owner chooses: hold with verified stop, or flatten |
| Risk-limit activation | Hold with verified broker stop; no modifications |
| Data-health activation | Hold with verified broker stop; re-verify stop via broker API |
| Broker-health activation | Hold; no modifications; escalate to owner immediately |
| Stop-loss failure activation | **Flatten immediately at market** |
| Drawdown activation | Hold with verified broker stop until the flatten window |
| Configuration-integrity activation | **Flatten immediately at market** |

In every case: disable new entries, cancel pending entries where safe,
notify the owner, write an incident record.

## Watchdog (§8.1, N-7)

Every service maintains a heartbeat; staleness beyond threshold halts new
entries and raises a mobile alert. A failure to flatten at the session
boundary is a broker-health trigger with immediate owner escalation (§14).

## Restart discipline (§18)

After any restart: load state → query broker (authoritative) → reconcile →
verify stops → halted/manage-only if uncertain → no new entries until
health restores.

## Recording

Every incident gets a record under `reports/incidents/` (timestamped,
append-only spirit: never edit a past incident report; add follow-ups) and a
line in `governance/decision-log.md` if it changed any decision or config.
Post-incident review feeds the learning loop (§15) via the Learning and
Audit Director.
