"""Shared planner-service errors.

Kept in their own module so ``generate`` / ``persist`` / ``shopping`` can all raise and catch
the same type without importing one another.
"""

from __future__ import annotations


class PlannerError(Exception):
    """A planner operation was refused for a reason the caller can act on and surface — a plan
    whose profile has been deleted, a regeneration with nothing left to roll.
    """


__all__ = ["PlannerError"]
