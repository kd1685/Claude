"""Per-action permission model for control actions.

Roles: officer < admin. Most actions are available to any officer; ranking
someone to R5 (kingdom leader) is admin-only and handled specially in the
change-rank endpoint.
"""
from __future__ import annotations

ROLE_LEVEL = {"officer": 1, "admin": 2}

# Minimum role required for each control action.
ACTION_MIN_ROLE = {
    "locate": "officer",
    "scan": "officer",
    "give_title": "officer",
    "rotation": "officer",
    "change_rank": "officer",   # except new_rank == 5 (see endpoint), admin-only
}


def level(role: str) -> int:
    return ROLE_LEVEL.get(role, 0)


def can(role: str, action: str) -> bool:
    return level(role) >= level(ACTION_MIN_ROLE.get(action, "admin"))


def permissions_for(role: str) -> dict:
    """Map of action -> bool for a role, for the UI to show/hide controls."""
    perms = {action: can(role, action) for action in ACTION_MIN_ROLE}
    # R5 promotions are always admin-only regardless of the change_rank flag.
    perms["change_rank_r5"] = role == "admin"
    return perms
