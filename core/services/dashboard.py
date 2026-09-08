"""The home dashboard read model (``Plan/12-Home-Dashboard/design.md``, "Reading the
dashboard").

``build_dashboard(user)`` runs every panel's query once and returns a ``DashboardContext``
dataclass with one attribute per panel. The view (and the future ``GET /api/dashboard/``)
assemble nothing — they loop over what they are handed. The REST API and the HTMX UI share
this layer so no panel rule is written twice (``ARCHITECTURE.md``, section 6).

**Every panel query goes through ``.visible_to(user)``.** A row a panel would otherwise render
from stored state (a recently-viewed object, a favourited object) is re-resolved live, because
access can have been revoked since (``design.md``, "Security notes"). "Shared with you"
(explicit shares) and "Public from others" (visible only because ``PUBLIC``) both show the
object and its owner's username only — never the rest of ``shared_with`` (D35) — and an
object belongs to exactly one of the two.

**Panels with nothing to say are absent** (``None`` / empty list), so the template renders no
empty boxes. ``sections`` is the exception: the five section links are the floor the page
degrades to and are always present.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from core.services.recent import RECENT_LIMIT, recent_for
from lists.models import List
from lists.services import AisleGroup, group_by_aisle
from meals.models import Dish, DishStats, RecipeBook
from planner.models import MealPlan, MealPlanEntry, MealSlot
from recipes.models import Recipe, RecipeStats

#: "This week" shows today plus the next couple of days, not the whole plan.
THIS_WEEK_DAYS = 3

#: First few unchecked shopping items shown on the dashboard; the rest are one click away.
SHOPPING_PREVIEW_LIMIT = 8

#: Caps on the list panels — a dashboard panel is a glance, not a full listing.
#: ``RECENT_LIMIT`` is defined once in ``core.services.recent`` and re-exported here.
FAVOURITES_LIMIT = 8
SHARED_WITH_YOU_LIMIT = 8
PUBLIC_FROM_OTHERS_LIMIT = 8

_SLOT_ORDER = {MealSlot.BREAKFAST: 0, MealSlot.LUNCH: 1, MealSlot.DINNER: 2}


# --- panel payloads -------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedSlot:
    slot: str
    slot_label: str
    dish_name: str | None
    dish_url: str | None


@dataclass(frozen=True)
class PlannedDay:
    date: datetime.date
    day_index: int
    is_today: bool
    slots: list[PlannedSlot]


@dataclass(frozen=True)
class ThisWeekPanel:
    plan_id: int
    plan_name: str
    plan_url: str
    days: list[PlannedDay]


@dataclass(frozen=True)
class ShoppingPanel:
    list_id: int
    name: str
    url: str
    checked: int
    total: int
    groups: list[AisleGroup]
    hidden_unchecked: int


@dataclass(frozen=True)
class EmptyPanel:
    """A flagship panel ("This week" / "Shopping") with nothing to show yet.

    Unlike the other five panels, which hide entirely when empty, these two always render — as
    a one-line call to action pointing the user at the route that fills them (``design.md``,
    the panel table). ``forward_url`` is the only payload and the discriminator the partials
    branch on: a real ``ThisWeekPanel`` / ``ShoppingPanel`` has no such attribute.
    """

    forward_url: str


@dataclass(frozen=True)
class ObjectCard:
    """A single owned object reduced to what a panel may render — never the share audience."""

    kind: str
    name: str
    url: str
    owner_username: str | None = None


@dataclass(frozen=True)
class SectionCount:
    label: str
    url: str
    count: int


@dataclass(frozen=True)
class DashboardContext:
    this_week: ThisWeekPanel | EmptyPanel
    shopping: ShoppingPanel | EmptyPanel
    recently_viewed: list[ObjectCard]
    favourites: list[ObjectCard]
    shared_with_you: list[ObjectCard]
    public_from_others: list[ObjectCard]
    suggestion: ObjectCard | None
    sections: list[SectionCount]
    show_get_started: bool = field(default=False)


# --- the builder --------------------------------------------------------------------------


def build_dashboard(user: object) -> DashboardContext:
    """Assemble every panel for ``user``'s home page."""
    this_week = _this_week(user)
    shopping = _shopping(user)
    recently_viewed = _recently_viewed(user)
    favourites = _favourites(user)
    shared_with_you = _shared_with_you(user)
    public_from_others = _public_from_others(user)
    suggestion = _suggestion(user)
    sections = _sections(user)

    has_activity = any(
        (
            isinstance(this_week, ThisWeekPanel),
            isinstance(shopping, ShoppingPanel),
            recently_viewed,
            favourites,
            shared_with_you,
            public_from_others,
            suggestion,
        )
    )
    has_content = any(section.count for section in sections)
    return DashboardContext(
        this_week=this_week,
        shopping=shopping,
        recently_viewed=recently_viewed,
        favourites=favourites,
        shared_with_you=shared_with_you,
        public_from_others=public_from_others,
        suggestion=suggestion,
        sections=sections,
        show_get_started=not has_activity and not has_content,
    )


# --- this week ---------------------------------------------------------------------------


def _this_week(user: object) -> ThisWeekPanel | EmptyPanel:
    """The plan the user owns whose date range covers today (``design.md``, "Edge cases": a
    plan that ended yesterday is *not* this week — show the empty CTA, not the last plan).
    """
    today = timezone.localdate()
    plan = (
        MealPlan.objects.visible_to(user)
        .filter(owner=user, start_date__lte=today)
        .order_by("-start_date")
        .first()
    )
    if plan is None or plan.start_date + datetime.timedelta(days=plan.days - 1) < today:
        return EmptyPanel(forward_url=reverse("planner:plan-generate"))

    today_index = (today - plan.start_date).days
    last_index = min(plan.days - 1, today_index + THIS_WEEK_DAYS - 1)

    entries = list(plan.entries.filter(day_index__gte=today_index, day_index__lte=last_index))
    visible_dishes = {
        dish.pk: dish
        for dish in Dish.objects.visible_to(user).filter(
            pk__in={e.dish_id for e in entries if e.dish_id is not None}
        )
    }
    slot_labels = dict(MealSlot.choices)

    by_day: dict[int, list[MealPlanEntry]] = {}
    for entry in entries:
        by_day.setdefault(entry.day_index, []).append(entry)

    days: list[PlannedDay] = []
    for day_index in range(today_index, last_index + 1):
        slots = []
        for entry in sorted(by_day.get(day_index, []), key=lambda e: _SLOT_ORDER.get(e.slot, 99)):
            dish = visible_dishes.get(entry.dish_id) if entry.dish_id is not None else None
            slots.append(
                PlannedSlot(
                    slot=entry.slot,
                    slot_label=slot_labels.get(entry.slot, entry.slot),
                    dish_name=dish.name if dish is not None else None,
                    dish_url=(dish.get_absolute_url() if dish is not None else None),
                )
            )
        days.append(
            PlannedDay(
                date=plan.start_date + datetime.timedelta(days=day_index),
                day_index=day_index,
                is_today=day_index == today_index,
                slots=slots,
            )
        )

    return ThisWeekPanel(
        plan_id=plan.pk,
        plan_name=plan.name or "Meal plan",
        plan_url=reverse("planner:plan-detail", args=[plan.pk]),
        days=days,
    )


# --- shopping ---------------------------------------------------------------------------


def _shopping(user: object) -> ShoppingPanel | EmptyPanel:
    """The user's *default* shopping list only — task 07's single-default-per-owner constraint
    (``design.md``, "Edge cases": the others are one click away on the lists page).
    """
    shopping_list = (
        List.objects.visible_to(user).filter(owner=user, is_default_shopping_list=True).first()
    )
    if shopping_list is None:
        return EmptyPanel(forward_url=reverse("lists:index"))

    counts = shopping_list.items.aggregate(
        total=Count("id"),
        checked=Count("id", filter=Q(is_checked=True)),
    )
    unchecked_qs = (
        shopping_list.items.filter(is_checked=False)
        .select_related("ingredient", "recipe", "dish", "unit")
        .prefetch_related("ingredient__tags")
        .order_by("position", "id")
    )
    unchecked_total = counts["total"] - counts["checked"]
    preview = list(unchecked_qs[:SHOPPING_PREVIEW_LIMIT])
    groups = group_by_aisle(preview, viewer=user)

    return ShoppingPanel(
        list_id=shopping_list.pk,
        name=shopping_list.name,
        url=shopping_list.get_absolute_url(),
        checked=counts["checked"],
        total=counts["total"],
        groups=groups,
        hidden_unchecked=max(0, unchecked_total - len(preview)),
    )


# --- recently viewed ------------------------------------------------------------------------

_KIND_LABELS = {"recipe": "Recipe", "dish": "Dish", "recipebook": "Book"}


def _card_for(obj: object, *, owner_username: str | None = None) -> ObjectCard:
    model_name = obj._meta.model_name
    return ObjectCard(
        kind=_KIND_LABELS.get(model_name, model_name),
        name=obj.name,
        url=obj.get_absolute_url(),
        owner_username=owner_username,
    )


def _recently_viewed(user: object) -> list[ObjectCard]:
    """The last few recipes / dishes / books the user opened, newest first, each re-resolved
    through ``.visible_to`` (``core.services.recent.recent_for``).
    """
    return [_card_for(obj) for obj in recent_for(user, limit=RECENT_LIMIT)]


# --- favourites -------------------------------------------------------------------------


def _favourites(user: object) -> list[ObjectCard]:
    """Favourited recipes and dishes (``RecipeStats`` / ``DishStats``, D3), intersected with
    ``.visible_to`` — a favourite can have been un-shared since (``design.md``, "Security
    notes").
    """
    recipe_ids = RecipeStats.objects.filter(user=user, is_favorite=True).values_list(
        "recipe_id", flat=True
    )
    dish_ids = DishStats.objects.filter(user=user, is_favorite=True).values_list(
        "dish_id", flat=True
    )
    recipes = (
        Recipe.objects.visible_to(user)
        .filter(pk__in=recipe_ids)
        .order_by("name")[:FAVOURITES_LIMIT]
    )
    dishes = (
        Dish.objects.visible_to(user).filter(pk__in=dish_ids).order_by("name")[:FAVOURITES_LIMIT]
    )

    recipe_cards = [_card_for(obj) for obj in recipes]
    dish_cards = [_card_for(obj) for obj in dishes]

    # Neither kind crowds the other out: reserve half the slots for each, then backfill any
    # unused slots from whichever kind has more (a user with 8+ favourite recipes must still
    # see their favourite dishes).
    half = FAVOURITES_LIMIT // 2
    cards = recipe_cards[:half] + dish_cards[:half] + recipe_cards[half:] + dish_cards[half:]
    return cards[:FAVOURITES_LIMIT]


# --- from other users ------------------------------------------------------------------


def _cards_from_others(
    user: object, *, narrow: Callable[[object], object], limit: int
) -> list[ObjectCard]:
    """Recipes / dishes / books owned by someone else, most-recently-updated first (12.9:
    there is no share timestamp, so ``updated_at`` stands in for "recently"). ``narrow`` is
    applied to each model's ``.visible_to(user)`` queryset to pick which subset this panel
    wants. Renders the object and its owner's username only — never the rest of the share
    audience (D35).
    """
    found: list[tuple[datetime.datetime, ObjectCard]] = []
    for model in (Recipe, Dish, RecipeBook):
        rows = (
            narrow(model.objects.visible_to(user))
            .select_related("owner")
            .order_by("-updated_at")[:limit]
        )
        for obj in rows:
            found.append((obj.updated_at, _card_for(obj, owner_username=obj.owner.username)))

    found.sort(key=lambda pair: pair[0], reverse=True)
    return [card for _, card in found[:limit]]


def _shared_with_you(user: object) -> list[ObjectCard]:
    """Objects another user has **explicitly shared** with ``user`` (``shared_with`` contains
    them). PUBLIC objects the user was never shared on belong to ``_public_from_others``, not
    here — an object appears in exactly one of the two panels (``design.md``, "Security
    notes").
    """
    return _cards_from_others(
        user,
        narrow=lambda qs: qs.filter(shared_with=user).exclude(owner=user),
        limit=SHARED_WITH_YOU_LIMIT,
    )


def _public_from_others(user: object) -> list[ObjectCard]:
    """Objects owned by someone else that ``user`` can see **only because they are PUBLIC** —
    ``.visible_to(user)`` minus their own, minus system rows, minus anything explicitly shared
    with them (which ``_shared_with_you`` already covers).
    """
    return _cards_from_others(
        user,
        narrow=lambda qs: qs.exclude(owner=user).exclude(is_system=True).exclude(shared_with=user),
        limit=PUBLIC_FROM_OTHERS_LIMIT,
    )


# --- what should I make? -----------------------------------------------------------------


def _suggestion(user: object) -> ObjectCard | None:
    """One randomly chosen visible dish, re-rollable through its fragment endpoint (12.13).
    Excludes dishes with no components, matching the planner's rule (task 06 ``design.md``).
    """
    dish = (
        Dish.objects.visible_to(user)
        .annotate(_component_count=Count("components"))
        .filter(_component_count__gt=0)
        .order_by("?")
        .first()
    )
    return _card_for(dish) if dish is not None else None


# --- sections -------------------------------------------------------------------------


def _sections(user: object) -> list[SectionCount]:
    """The five section links — always present, each with a visibility-scoped count."""
    return [
        SectionCount(
            "Recipes", reverse("recipes:recipe-list"), Recipe.objects.visible_to(user).count()
        ),
        SectionCount("Dishes", reverse("meals:dish-list"), Dish.objects.visible_to(user).count()),
        SectionCount(
            "Books", reverse("meals:book-list"), RecipeBook.objects.visible_to(user).count()
        ),
        SectionCount("Lists", reverse("lists:index"), List.objects.visible_to(user).count()),
        SectionCount(
            "Meal plans", reverse("planner:index"), MealPlan.objects.visible_to(user).count()
        ),
    ]
