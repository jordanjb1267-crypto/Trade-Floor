"""Owner notification paths (§18): outbound, advisory, deterministic.

§18 lists "Local notifications plus optional Telegram/Discord notification
path" among the minimum operational requirements. Modules here carry text
OUT to the owner and nothing back in; none of them may import broker code
or hold any primitive that could reach an order path (§0 iron rule 1).
"""
