"""Push a saved plan's dishes to a shopping list (``Plan/08-Meal-Planner/tasks.md`` 08.8).

**Pure orchestration.** Every hard part — flattening, sub-recipe yield scaling, cross-dish
aggregation, replace-only-this-plan's-generated-items — already lives in tasks 05–07.
:func:`generate_shopping_list` just calls task 07's ``populate_shopping_list`` with the plan's
dishes and itself as ``source_plan``; :func:`preview_shopping_list` calls task 07's read-only
``preview_shopping_list``. No flatten / aggregate / scale logic is written here — if it ever
seems necessary, it belongs back in 05/06/07 (``design.md``: *"This task only orchestrates"*).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lists.services import (
    ShoppingPreview,
    ShoppingResult,
    get_or_create_default_shopping_list,
    populate_shopping_list,
)
from lists.services import preview_shopping_list as _preview_lines

if TYPE_CHECKING:
    from planner.models import MealPlan


def staples_default(plan: MealPlan) -> bool:
    """Whether to drop staples when the caller passed nothing explicit: the live profile's
    ``exclude_staples`` if the profile still exists, else the value frozen into the plan's
    snapshot, else ``True`` (the design default). The one fallback both the services and the
    HTML views (B4) use, so the toggle's pre-checked state can never disagree with what
    generation would actually do.
    """
    if plan.profile is not None:
        return plan.profile.exclude_staples
    return bool((plan.profile_snapshot or {}).get("exclude_staples", True))


def _planned_dishes(plan: MealPlan) -> list:
    """The distinct-per-entry dish list — one element per *filled* entry, repeats kept.

    A dish scheduled twice is passed twice on purpose: ``populate_shopping_list`` sums it to
    2x, because a repeated dinner needs double the groceries (task 07, D42).
    """
    return [
        entry.dish
        for entry in plan.entries.select_related("dish").all()
        if entry.dish_id is not None
    ]


def generate_shopping_list(
    plan: MealPlan, *, exclude_staples: bool | None = None
) -> ShoppingResult:
    """Flatten every planned dish onto ``plan.shopping_list`` (or the owner's default list,
    created and linked if the plan has none), replacing only the items this plan generated
    before (C8). Manual items and other plans' generated items are untouched.

    ``exclude_staples`` defaults to the plan's profile / snapshot preference.
    """
    if exclude_staples is None:
        exclude_staples = staples_default(plan)

    lst = plan.shopping_list or get_or_create_default_shopping_list(plan.owner)
    # ``populate_shopping_list`` does its bounded flatten / aggregate / recipe-graph walk
    # before opening its own write transaction — no outer ``atomic()`` here, so that compute
    # is never held inside ``BEGIN IMMEDIATE`` (08.20 review; ARCHITECTURE §2). If the link
    # save below fails, the next run repopulates and links (``replace_generated`` scopes the
    # delete to this plan, so the window is self-healing).
    result = populate_shopping_list(
        lst,
        _planned_dishes(plan),
        source_plan=plan,
        exclude_staples=exclude_staples,
        replace_generated=True,
    )
    if plan.shopping_list_id != lst.pk:
        plan.shopping_list = lst
        plan.save(update_fields=["shopping_list"])
    return result


def preview_shopping_list(
    plan: MealPlan, *, exclude_staples: bool | None = None
) -> ShoppingPreview:
    """The ingredient lines ``generate_shopping_list`` would write — nothing is written, no
    list is created or linked.
    """
    if exclude_staples is None:
        exclude_staples = staples_default(plan)
    return _preview_lines(plan.owner, _planned_dishes(plan), exclude_staples=exclude_staples)


__all__ = ["generate_shopping_list", "preview_shopping_list", "staples_default"]
