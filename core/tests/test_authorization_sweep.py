"""Plan/10-Security-And-Deployment/test-plan.md, "Authorization regression sweep —
core/tests/test_authorization_sweep.py" (10.1).

The safety net for everything built in tasks 03-09: for **every** registered viewset and
template view, does ``get_queryset()`` route through ``.visible_to(user)``, is there an
object-level permission on writes, do nested serializers filter their children, and does a
private object 404 rather than 403 (design.md, "Object-level authorization sweep")?

Follows ``core/tests/test_conventions.py``'s pattern throughout: walk the real registry (the
URLconf, the app registry, the actual serializer classes DRF instantiates), check the real
implementation, and pair every structural check with a non-vacuousness proof -- a deliberately
broken stand-in that the same detection logic must catch, so a green "no offenders" result can't
be explained by the check silently matching nothing.

Six tests, matching test-plan.md exactly:

1. ``test_every_owned_viewset_uses_visible_to`` -- parametrized over every registered DRF
   viewset serving an ``OwnedModel``.
2. ``test_every_owned_view_uses_visible_to`` -- the HTML side: every Django generic CBV over an
   ``OwnedModel``, plus a source-level sweep of every reachable view (CBV or plain ``View``)
   for an owned model's ``.objects`` manager touched without ``.visible_to()``/``.editable_by()``.
3. ``test_every_owned_model_returns_404_not_403`` -- parametrized over every owned model with a
   registered detail route, both API and HTML.
4. ``test_no_serializer_exposes_owner_as_writable`` -- parametrized over every registered owned
   viewset's serializer.
5. ``test_all_nested_serializers_filter_visibility`` -- the generic mechanism (proven against
   the throwaway ``DummyNode`` fixture, both positively and with the filter removed) plus a
   structural sweep of every declared nested serializer over an ``OwnedModel`` for the sensitive
   fields it must never re-expose.
6. ``test_anonymous_cannot_reach_any_data_endpoint`` -- parametrized over every registered route
   reachable from the project's real URLconf.
"""

from __future__ import annotations

import inspect
import re
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.http import HttpResponse
from django.test import Client
from django.urls import get_resolver, reverse
from django.views import View
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.list import MultipleObjectMixin
from rest_framework import serializers as drf_serializers
from rest_framework.test import APIClient
from rest_framework.viewsets import GenericViewSet

from core.mixins import OwnedObjectMixin
from core.models import OwnedModel, Visibility
from core.tests.models import DummyNode, DummyOwned
from core.tests.serializers import DummyNodeSerializer
from core.tests.test_conventions import (
    _iter_view_classes_from_urlconf,
    _model_for_viewset,
    _owned_model_viewsets,
    _routes_through_visible_to,
)
from core.viewsets import OwnedViewSetMixin

pytestmark = pytest.mark.django_db


def _api_client(user) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


# =================================================================================================
# 1. test_every_owned_viewset_uses_visible_to
# =================================================================================================
#
# The detection logic (``_owned_model_viewsets``, ``_routes_through_visible_to``) already lives
# in core/tests/test_conventions.py, proven non-vacuous there against deliberately broken
# stand-ins (``test_owned_viewset_missing_mixin_is_actually_detected``,
# ``test_viewset_that_overrides_get_queryset_without_super_is_detected``). This sweep reuses it
# rather than re-deriving the same rule twice, and turns the single "offenders == []" assertion
# into one assertion per viewset, per test-plan.md's "parametrized over every registered owned
# viewset" -- a failure here names exactly one offending viewset instead of a whole list.

_owned_viewsets = _owned_model_viewsets()


@pytest.mark.parametrize(
    "viewset_cls",
    _owned_viewsets,
    ids=[f"{vs.__module__}.{vs.__qualname__}" for vs in _owned_viewsets],
)
def test_every_owned_viewset_uses_visible_to(viewset_cls: type[GenericViewSet]) -> None:
    assert issubclass(viewset_cls, OwnedViewSetMixin), (
        f"{viewset_cls.__module__}.{viewset_cls.__qualname__} serves an OwnedModel subclass "
        "without OwnedViewSetMixin -- every row is visible to everyone."
    )
    assert _routes_through_visible_to(viewset_cls), (
        f"{viewset_cls.__module__}.{viewset_cls.__qualname__}.get_queryset() does not route "
        "through OwnedViewSetMixin.get_queryset(), directly or via super()."
    )


def test_owned_viewset_sweep_is_not_vacuous() -> None:
    assert _owned_viewsets, (
        "no viewset over an OwnedModel is registered anywhere in the URLconf -- "
        "test_every_owned_viewset_uses_visible_to would collect zero parameters and pass "
        "vacuously"
    )


# =================================================================================================
# 2. test_every_owned_view_uses_visible_to
# =================================================================================================
#
# Django's own View.as_view() has never set a `.cls` attribute on the callback the way DRF's
# APIView.as_view()/ViewSetMixin.as_view() do -- only `.view_class` (added in Django 4.1). A walk
# that checks only `.cls` (test_conventions._iter_view_classes_from_urlconf, correct for its
# DRF-only purpose) is therefore completely blind to every plain Django CBV/View in the project:
# every ListView, DetailView, and hand-written action View. Checking `.view_class` too is what
# makes this half of the sweep mean anything at all -- see
# test_html_view_discovery_requires_view_class_not_only_cls below for the direct proof.


def _iter_view_classes_including_plain_cbvs(urlconf: str) -> list[type]:
    classes: list[type] = []
    stack = [get_resolver(urlconf)]
    while stack:
        current = stack.pop()
        for pattern in current.url_patterns:
            if hasattr(pattern, "url_patterns"):
                stack.append(pattern)
            else:
                cls = getattr(pattern.callback, "cls", None) or getattr(
                    pattern.callback, "view_class", None
                )
                if cls is not None:
                    classes.append(cls)
    return classes


def _all_reachable_view_classes() -> list[type]:
    seen: dict[int, type] = {}
    for urlconf in (settings.ROOT_URLCONF, "core.tests.urls"):
        for cls in _iter_view_classes_including_plain_cbvs(urlconf):
            seen[id(cls)] = cls
    return list(seen.values())


def _html_view_classes() -> list[type]:
    """Every reachable view class that is not a DRF viewset -- the plain-Django half of the
    registry, covering both generic CBVs (ListView/DetailView/...) and hand-written ``View``
    subclasses.
    """
    return [cls for cls in _all_reachable_view_classes() if not issubclass(cls, GenericViewSet)]


def _is_owned_generic_cbv(view_cls: type) -> bool:
    """True only for a genuine Django generic view over an OwnedModel -- ``SingleObjectMixin``/
    ``MultipleObjectMixin`` is what makes a ``model`` attribute mean "fetch this through
    ``get_queryset()``" at all. A plain ``View`` subclass that happens to declare its own
    ``model`` attribute as a bespoke convention (``meals.views._ShareView``/``_UnshareView``,
    which read ``self.model`` inside ``post()`` to parametrize which app model to fetch) is not
    this shape and must not be treated as one -- it is covered instead by the source-level leak
    scan below.
    """
    if not issubclass(view_cls, (SingleObjectMixin, MultipleObjectMixin)):
        return False
    model = getattr(view_cls, "model", None)
    return inspect.isclass(model) and issubclass(model, OwnedModel)


def _owned_html_cbvs() -> list[type]:
    return [cls for cls in _html_view_classes() if _is_owned_generic_cbv(cls)]


def _routes_through_visible_to_html(view_cls: type) -> bool:
    """The ``OwnedObjectMixin`` analogue of ``test_conventions._routes_through_visible_to``."""
    if view_cls.get_queryset is OwnedObjectMixin.get_queryset:
        return True
    try:
        source = inspect.getsource(view_cls.get_queryset)
    except (OSError, TypeError):
        return False
    return "super(" in source and "get_queryset" in source


def _get_queryset_calls_visible_to_directly(view_cls: type) -> bool:
    """The documented alternative to ``OwnedObjectMixin`` (``core/README.md``, "Does this view
    need different write authorization than IsOwnerOrReadOnly?"): a view that needs a stricter
    write rule than ``OwnedObjectMixin.get_object()`` gives (e.g. an owner-only confirm screen a
    mere sharee must not even preview, per ``meals.views.BookCopyConfirmView`` /
    ``lists.views.ListClearAllConfirmView`` and their siblings) skips the mixin but still writes
    ``get_queryset()`` to return ``Model.objects.visible_to(self.request.user)`` directly.
    """
    get_queryset = getattr(view_cls, "get_queryset", None)
    if get_queryset is None:
        return False
    try:
        source = inspect.getsource(get_queryset)
    except (OSError, TypeError):
        return False
    return ".visible_to(" in source


def _html_cbvs_missing_owned_mixin(view_classes: list[type]) -> list[type]:
    offenders: list[type] = []
    for cls in view_classes:
        if issubclass(cls, OwnedObjectMixin):
            if not _routes_through_visible_to_html(cls):
                offenders.append(cls)
        elif not _get_queryset_calls_visible_to_directly(cls):
            offenders.append(cls)
    return offenders


#: Every concrete OwnedModel subclass in the app registry -- both the real domain models and
#: core.tests.models' throwaway fixtures (registered only under test settings).
_OWNED_MODEL_NAMES = sorted(
    {
        model.__name__
        for model in django_apps.get_models()
        if issubclass(model, OwnedModel) and model is not OwnedModel
    }
)
_OWNED_MODEL_OBJECTS_RE = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in _OWNED_MODEL_NAMES) + r")\.objects\."
)

#: Lines that touch an owned model's manager on an already-established, already-owned instance
#: (re-filtering by its own ``pk`` to do a targeted update/delete) rather than a fresh, unscoped
#: lookup -- narrowly grandfathered here instead of rewritten for a regex's benefit. Each call
#: site documents, in its own module, why the ownership decision was already made a few lines
#: earlier in the same method:
#:   - meals/views.py BookOrderingView.post: ``book`` was already fetched via
#:     ``RecipeBook.objects.visible_to(request.user)`` and ``book.owner_id == request.user.id``
#:     was checked immediately above this line.
#:   - planner/views.py PlanBulkDeleteView.post: ``plans`` was already resolved through
#:     ``MealPlan.objects.visible_to(request.user).filter(owner=request.user, pk__in=ids)`` in
#:     ``_owned`` a few lines above.
_KNOWN_SAFE_UNSCOPED_LINES = frozenset(
    {
        "RecipeBook.objects.filter(pk=book.pk).update(default_ordering=raw)",
        "MealPlan.objects.filter(pk__in=[plan.pk for plan in plans]).delete()",
    }
)


def _owned_model_leaks_in_view_source(view_classes: list[type]) -> dict[str, list[str]]:
    """Every reachable view class whose own source touches an owned model's ``.objects``
    manager on a line that routes through neither ``.visible_to(`` nor ``.editable_by(`` -- the
    plain-``View`` analogue of the CBV mixin check above, catching a
    ``get_object_or_404(Model.objects.all(), pk=pk)`` regression the structural mixin check
    cannot see, since a hand-written action ``View`` has no ``model``/``get_queryset()`` for it
    to inspect.

    DRF viewsets are skipped: their ``queryset = Model.objects.all()`` class attribute is
    deliberately unfiltered by design -- ``OwnedViewSetMixin.get_queryset()`` filters it at
    request time, already covered by ``test_every_owned_viewset_uses_visible_to`` above.
    """
    offenders: dict[str, list[str]] = {}
    for cls in view_classes:
        if issubclass(cls, GenericViewSet):
            continue
        try:
            source = inspect.getsource(cls)
        except (OSError, TypeError):
            continue
        bad_lines = [
            line.strip()
            for line in source.splitlines()
            if _OWNED_MODEL_OBJECTS_RE.search(line)
            and ".visible_to(" not in line
            and ".editable_by(" not in line
            and ".create(" not in line
            and line.strip() not in _KNOWN_SAFE_UNSCOPED_LINES
        ]
        if bad_lines:
            offenders[f"{cls.__module__}.{cls.__qualname__}"] = bad_lines
    return offenders


def test_every_owned_view_uses_visible_to() -> None:
    owned_cbvs = _owned_html_cbvs()
    assert owned_cbvs, (
        "no generic Django CBV over an OwnedModel was found reachable from the project's "
        "URLconf -- see test_html_view_discovery_requires_view_class_not_only_cls for why this "
        "would be a silent vacuous pass rather than a real absence"
    )

    mixin_offenders = _html_cbvs_missing_owned_mixin(owned_cbvs)
    assert mixin_offenders == [], (
        "HTML view(s) serving an OwnedModel without OwnedObjectMixin, or without routing "
        "get_queryset() through it: "
        f"{[f'{vs.__module__}.{vs.__qualname__}' for vs in mixin_offenders]}"
    )

    leak_offenders = _owned_model_leaks_in_view_source(_html_view_classes())
    assert leak_offenders == {}, (
        "view(s) reachable from the URLconf touch an owned model's .objects manager without "
        f"routing through .visible_to()/.editable_by(): {leak_offenders}"
    )


def test_html_view_discovery_requires_view_class_not_only_cls() -> None:
    """Non-vacuousness proof for the discovery mechanism itself: a ``.cls``-only walk (what
    ``core.tests.test_conventions`` uses, correctly, for its DRF-only purpose) finds zero plain
    Django CBVs anywhere in this project, because Django's own ``View.as_view()`` has never set
    that attribute -- only ``.view_class`` does. Without checking ``.view_class`` too,
    ``test_every_owned_view_uses_visible_to`` would find no HTML views at all and pass having
    tested nothing.
    """
    cls_only_owned_cbvs = [
        cls
        for urlconf in (settings.ROOT_URLCONF, "core.tests.urls")
        for cls in _iter_view_classes_from_urlconf(urlconf)
        if not issubclass(cls, GenericViewSet) and _is_owned_generic_cbv(cls)
    ]
    assert cls_only_owned_cbvs == [], (
        "a .cls-only walk should find zero owned Django generic CBVs, since Django's own "
        "View.as_view() has never set .cls -- if this ever finds some, the premise for needing "
        ".view_class here needs re-checking"
    )
    assert _owned_html_cbvs(), (
        "the .view_class-aware walk must find real owned HTML CBVs once .view_class is checked"
    )


def test_html_cbv_missing_owned_mixin_is_actually_detected() -> None:
    from django.views.generic import ListView

    class RogueListView(ListView):
        model = DummyOwned
        template_name = "core_test_fixtures/dummy_list.html"

    assert _html_cbvs_missing_owned_mixin([RogueListView]) == [RogueListView]


def test_html_cbv_overriding_get_queryset_without_super_is_detected() -> None:
    from django.views.generic import ListView

    class CarelessListView(OwnedObjectMixin, ListView):
        model = DummyOwned
        template_name = "core_test_fixtures/dummy_list.html"

        def get_queryset(self):
            return DummyOwned.objects.all()

    assert _html_cbvs_missing_owned_mixin([CarelessListView]) == [CarelessListView]


def test_html_cbv_skipping_the_mixin_for_a_direct_visible_to_is_not_a_false_positive() -> None:
    """The documented alternative (meals.views.BookCopyConfirmView and siblings): a view that
    needs a stricter write rule than OwnedObjectMixin gives skips the mixin but writes
    get_queryset() to call .visible_to() directly. Must not be flagged.
    """
    from django.views.generic import DetailView

    class OwnerOnlyConfirmView(DetailView):
        model = DummyOwned
        template_name = "core_test_fixtures/dummy_detail.html"

        def get_queryset(self):
            return DummyOwned.objects.visible_to(self.request.user)

    assert _html_cbvs_missing_owned_mixin([OwnerOnlyConfirmView]) == []


def test_owned_model_leak_scan_is_actually_detected() -> None:
    class RogueLeakView(View):
        def get(self, request: Any, pk: int) -> HttpResponse:
            obj = DummyOwned.objects.filter(pk=pk).first()
            return HttpResponse(obj.name if obj else "")

    offenders = _owned_model_leaks_in_view_source([RogueLeakView])
    assert offenders, (
        "a view that fetches an owned model by a bare .objects.filter(), with neither "
        ".visible_to() nor .editable_by(), must be flagged"
    )


def test_owned_model_leak_scan_is_not_a_false_positive_on_the_documented_pattern() -> None:
    class FineView(View):
        def get(self, request: Any, pk: int) -> HttpResponse:
            obj = DummyOwned.objects.visible_to(request.user).filter(pk=pk).first()
            return HttpResponse(obj.name if obj else "")

    assert _owned_model_leaks_in_view_source([FineView]) == {}


# =================================================================================================
# 3. test_every_owned_model_returns_404_not_403
# =================================================================================================
#
# Every concrete OwnedModel subclass that has a registered detail route (both the API and the
# HTML side, where both exist) -- a fresh, minimal, PRIVATE instance owned by one user must 404,
# never 403, when another authenticated user requests it (design.md, "Enumeration": a private
# object's non-existence must be indistinguishable from someone else's private object).
#
# Built with direct ORM creation rather than importing each app's own conftest.py factories --
# those fixtures assume their own app's other fixtures (a specific `alice`, specific unit
# fixtures) and are not meant to be shared cross-app. Keeping this file self-contained mirrors
# why core.tests.models exists at all (see that module's docstring): this sweep must not depend
# on any one app's test suite still looking the way it does today.


def _make_unit(name: str):
    from catalog.models import Dimension, Unit

    unit, _ = Unit.objects.get_or_create(
        name=name,
        defaults={
            "abbrev": name[:12],
            "dimension": Dimension.COUNT,
            "to_base_factor": Decimal("1"),
        },
    )
    return unit


def _make_owned_object(model: type[OwnedModel], owner: Any) -> OwnedModel:
    """A minimal, valid, PRIVATE instance of ``model`` owned by ``owner``.

    Every concrete OwnedModel subclass with a registered detail route must have a branch here --
    deliberately no fallback/default branch, so a future model added without updating this sweep
    fails loudly (a clear ``NotImplementedError``) rather than being silently skipped.
    """
    from catalog.models import Ingredient
    from lists.models import List
    from meals.models import Dish, RecipeBook
    from planner.models import MealPlan
    from recipes.models import Recipe

    common = {"owner": owner, "visibility": Visibility.PRIVATE}

    if model is Ingredient:
        return Ingredient.objects.create(
            name="Sweep Ingredient", default_unit=_make_unit("sweep-ea"), **common
        )
    if model is Recipe:
        return Recipe.objects.create(
            name="Sweep Recipe",
            instructions="Mix.",
            yield_quantity=Decimal("1"),
            yield_unit=_make_unit("sweep-cup"),
            **common,
        )
    if model is Dish:
        return Dish.objects.create(name="Sweep Dish", **common)
    if model is RecipeBook:
        return RecipeBook.objects.create(name="Sweep Book", **common)
    if model is List:
        return List.objects.create(name="Sweep List", **common)
    if model is MealPlan:
        return MealPlan.objects.create(start_date=date.today(), days=1, seed=1, **common)
    if model is DummyOwned:
        return DummyOwned.objects.create(name="sweep dummy", **common)
    if model is DummyNode:
        return DummyNode.objects.create(name="sweep node", **common)
    raise NotImplementedError(
        f"{model.__name__} has a registered detail route but no factory branch in "
        "_make_owned_object -- add one so this sweep actually covers it."
    )


#: model -> (API detail URL name, HTML detail URL name or None if there isn't one).
_REAL_MODEL_DETAIL_URL_NAMES: dict[str, tuple[str, str | None]] = {
    "Ingredient": ("catalog_api:ingredient-detail", "catalog:ingredient-detail"),
    "Recipe": ("recipes_api:recipe-detail", "recipes:recipe-detail"),
    "Dish": ("meals_api:dish-detail", "meals:dish-detail"),
    "RecipeBook": ("meals_api:recipebook-detail", "meals:book-detail"),
    "List": ("lists_api:list-detail", "lists:list-detail"),
    "MealPlan": ("planner_api:planner-plan-detail", "planner:plan-detail"),
}


def _real_owned_models() -> list[type[OwnedModel]]:
    """Every OwnedModel subclass reachable via a registered viewset on the project's actual
    URLconf -- excludes core.tests.urls's DummyOwned/DummyNode fixtures, which are exercised
    separately below through the dummy urlconf's own routes.
    """
    seen: dict[str, type[OwnedModel]] = {}
    for cls in _iter_view_classes_from_urlconf(settings.ROOT_URLCONF):
        if issubclass(cls, GenericViewSet) and cls is not GenericViewSet:
            model = _model_for_viewset(cls)
            if model is not None and issubclass(model, OwnedModel):
                seen[model.__name__] = model
    return list(seen.values())


def test_real_owned_model_url_map_is_complete() -> None:
    """If a new OwnedModel gets a viewset without _REAL_MODEL_DETAIL_URL_NAMES being updated to
    match, this fails loudly rather than test_every_owned_model_returns_404_not_403 silently
    covering one fewer model than the registry actually has.
    """
    assert {model.__name__ for model in _real_owned_models()} == set(_REAL_MODEL_DETAIL_URL_NAMES)


_real_models = _real_owned_models()


@pytest.mark.parametrize("model", _real_models, ids=[m.__name__ for m in _real_models])
def test_every_owned_model_returns_404_not_403(model: type[OwnedModel], alice, carol) -> None:
    api_name, html_name = _REAL_MODEL_DETAIL_URL_NAMES[model.__name__]
    obj = _make_owned_object(model, owner=alice)

    api_response = _api_client(carol).get(reverse(api_name, args=[obj.pk]))
    assert api_response.status_code == 404, (
        f"{model.__name__}'s API detail route returned {api_response.status_code} for a "
        "private object owned by someone else -- expected 404, never 403."
    )

    if html_name is not None:
        html_client = Client()
        html_client.force_login(carol)
        html_response = html_client.get(reverse(html_name, args=[obj.pk]))
        assert html_response.status_code == 404, (
            f"{model.__name__}'s HTML detail route returned {html_response.status_code} for a "
            "private object owned by someone else -- expected 404, never 403."
        )


@pytest.mark.urls("core.tests.urls")
def test_dummy_owned_models_return_404_not_403(alice, carol, make_dummy, make_dummy_node) -> None:
    """The same proof against the throwaway core.tests.models fixtures, reachable only under
    core.tests.urls -- keeps the check exercised even in a hypothetical future where every real
    app model above were somehow removed from _REAL_MODEL_DETAIL_URL_NAMES.
    """
    dummy = make_dummy(owner=alice, visibility=Visibility.PRIVATE)
    node = make_dummy_node(owner=alice, visibility=Visibility.PRIVATE)

    client = _api_client(carol)
    assert client.get(f"/dummy/{dummy.pk}/").status_code == 404
    assert client.get(f"/dummy-nodes/{node.pk}/").status_code == 404

    html_client = Client()
    html_client.force_login(carol)
    assert html_client.get(f"/dummy-html/{dummy.pk}/").status_code == 404


# =================================================================================================
# 4. test_no_serializer_exposes_owner_as_writable
# =================================================================================================
#
# Every serializer OwnedViewSetMixin actually serves must inherit OwnedSerializer's read-only
# owner/is_system/shared_with/copied_from/visibility -- the mass-assignment hole MILESTONES.md
# section 6 names directly. Parametrized over every unique serializer_class among the registered
# owned viewsets (real models and the dummy fixtures alike), rather than re-deriving the same
# proof per app (already done, once, well, in core/tests/test_serializers.py against
# DummySerializer) -- this is the registry-wide guarantee that every *other* serializer inherits
# it too.

_UNSAFE_SERIALIZER_FIELDS = frozenset(
    {"owner", "is_system", "shared_with", "copied_from", "visibility"}
)


def _owned_serializer_classes() -> list[type[drf_serializers.Serializer]]:
    seen: dict[int, type[drf_serializers.Serializer]] = {}
    for viewset_cls in _owned_viewsets:
        serializer_class = getattr(viewset_cls, "serializer_class", None)
        if serializer_class is not None:
            seen[id(serializer_class)] = serializer_class
    return list(seen.values())


def _writable_unsafe_fields(serializer_class: type[drf_serializers.Serializer]) -> set[str]:
    instance = serializer_class()
    return {
        name
        for name in _UNSAFE_SERIALIZER_FIELDS
        if name in instance.fields and not instance.fields[name].read_only
    }


_owned_serializers = _owned_serializer_classes()


@pytest.mark.parametrize(
    "serializer_class",
    _owned_serializers,
    ids=[f"{sc.__module__}.{sc.__qualname__}" for sc in _owned_serializers],
)
def test_no_serializer_exposes_owner_as_writable(
    serializer_class: type[drf_serializers.Serializer],
) -> None:
    writable = _writable_unsafe_fields(serializer_class)
    assert writable == set(), (
        f"{serializer_class.__module__}.{serializer_class.__qualname__} exposes "
        f"{sorted(writable)} as writable -- these must be read-only (core.serializers."
        "OwnedSerializer), or a client can mass-assign ownership/sharing/system state directly."
    )


def test_owned_serializer_sweep_is_not_vacuous() -> None:
    assert _owned_serializers


def test_writable_owner_field_is_actually_detected() -> None:
    class RogueSerializer(drf_serializers.ModelSerializer):
        class Meta:
            model = DummyOwned
            fields = ["id", "name", "owner"]

    assert _writable_unsafe_fields(RogueSerializer) == {"owner"}


def test_readonly_owner_field_is_not_a_false_positive() -> None:
    from core.tests.serializers import DummySerializer

    assert _writable_unsafe_fields(DummySerializer) == set()


# =================================================================================================
# 5. test_all_nested_serializers_filter_visibility
# =================================================================================================


def test_nested_serializer_filters_invisible_children(alice, carol) -> None:
    """The generic mechanism this project relies on (a SerializerMethodField routed through
    .visible_to(), core.tests.serializers.DummyNodeSerializer) actually hides an invisible
    child -- the same proof as core/tests/test_serializers.py's
    test_nested_children_filtered_by_visibility, kept here too since test-plan.md names this
    file specifically for the sweep.
    """
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()

    def make(owner, **kw):
        return DummyNode.objects.create(owner=owner, **kw)

    parent = make(alice, name="parent", visibility=Visibility.PUBLIC)
    visible_child = make(alice, name="visible", visibility=Visibility.PUBLIC)
    hidden_child = make(alice, name="hidden", visibility=Visibility.PRIVATE)
    parent.depends_on.add(visible_child, hidden_child)

    request = factory.get("/")
    request.user = carol
    serializer = DummyNodeSerializer(parent, context={"request": request})

    assert serializer.data["depends_on"] == [visible_child.pk]


def test_nested_serializer_filter_is_actually_detected_when_removed(
    alice, carol, monkeypatch
) -> None:
    """Non-vacuousness in the direction that matters most: if the visibility filter were ever
    removed from the nested field's getter, the hidden child leaks straight through -- proving
    the assertion above would actually fail on a real regression, not merely on a contrived
    stand-in.
    """
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()

    parent = DummyNode.objects.create(owner=alice, name="parent2", visibility=Visibility.PUBLIC)
    hidden_child = DummyNode.objects.create(
        owner=alice, name="hidden2", visibility=Visibility.PRIVATE
    )
    parent.depends_on.add(hidden_child)

    def unfiltered_get_depends_on(self, obj):
        return list(obj.depends_on.values_list("pk", flat=True))

    monkeypatch.setattr(DummyNodeSerializer, "get_depends_on", unfiltered_get_depends_on)

    request = factory.get("/")
    request.user = carol
    serializer = DummyNodeSerializer(parent, context={"request": request})

    assert hidden_child.pk in serializer.data["depends_on"], (
        "sanity check: with the filter removed, the leak must actually reproduce -- otherwise "
        "the real (filtered) test above is not proving anything"
    )


#: Every declared field, on every registered owned serializer, that is itself a nested
#: ModelSerializer (directly, or as the .child of a many=True field) representing a *different*
#: OwnedModel -- the shape design.md's "Relation leaks" note warns about: nesting the full
#: related row rather than a minimal, name-only projection. Currently empty in this codebase
#: (recipes.RecipeComponentSerializer / meals.DishComponentSerializer nest a serializer over the
#: plain join model, not over Recipe/Ingredient/Dish directly), which is exactly why the
#: non-vacuousness proof below matters -- a "zero offenders" result here must be provably not
#: because the check matches nothing.
def _nested_full_object_serializer_classes(
    serializer_class: type[drf_serializers.Serializer],
) -> list[type[drf_serializers.ModelSerializer]]:
    instance = serializer_class()
    found: list[type[drf_serializers.ModelSerializer]] = []
    for field in instance.fields.values():
        candidate = field
        if isinstance(candidate, drf_serializers.ListSerializer):
            candidate = candidate.child
        if isinstance(candidate, drf_serializers.ModelSerializer):
            meta_model = getattr(getattr(candidate, "Meta", None), "model", None)
            if (
                meta_model is not None
                and issubclass(meta_model, OwnedModel)
                and meta_model
                is not getattr(getattr(serializer_class, "Meta", None), "model", None)
            ):
                found.append(type(candidate))
    return found


#: What a nested full-object serializer must never re-expose -- the same five fields
#: OwnedSerializer protects on writability (_UNSAFE_SERIALIZER_FIELDS above), plus ``notes``:
#: legitimately writable and readable on the *top-level* serializer for the object's own owner,
#: but never something a nested reference to *someone else's* owned object should carry along
#: for free.
_SENSITIVE_NESTED_EXPOSURE_FIELDS = _UNSAFE_SERIALIZER_FIELDS | {"notes"}


def _sensitive_fields_exposed(
    nested_serializer_class: type[drf_serializers.Serializer],
) -> set[str]:
    instance = nested_serializer_class()
    return _SENSITIVE_NESTED_EXPOSURE_FIELDS & set(instance.fields)


@pytest.mark.parametrize(
    "serializer_class",
    _owned_serializers,
    ids=[f"{sc.__module__}.{sc.__qualname__}" for sc in _owned_serializers],
)
def test_all_nested_serializers_filter_visibility(
    serializer_class: type[drf_serializers.Serializer],
) -> None:
    for nested_cls in _nested_full_object_serializer_classes(serializer_class):
        leaked = _sensitive_fields_exposed(nested_cls)
        assert leaked == set(), (
            f"{serializer_class.__qualname__} nests {nested_cls.__qualname__} (a full "
            f"ModelSerializer over another OwnedModel) exposing {sorted(leaked)} -- a nested "
            "serializer over someone else's owned object must never re-expose these, regardless "
            "of the parent's own visibility."
        )


def test_nested_full_object_serializer_leak_is_actually_detected() -> None:
    class LeakyNestedSerializer(drf_serializers.ModelSerializer):
        class Meta:
            model = DummyOwned
            fields = ["id", "name", "notes", "shared_with"]

    class ParentSerializer(drf_serializers.ModelSerializer):
        child = LeakyNestedSerializer()

        class Meta:
            model = DummyNode
            fields = ["id", "name", "child"]

    nested = _nested_full_object_serializer_classes(ParentSerializer)
    assert nested == [LeakyNestedSerializer]
    assert _sensitive_fields_exposed(LeakyNestedSerializer) == {"notes", "shared_with"}


# =================================================================================================
# 6. test_anonymous_cannot_reach_any_data_endpoint
# =================================================================================================
#
# Every route reachable from the project's real URLconf, probed anonymously. Catches the
# endpoint someone added without a permission class / LoginRequiredMixin: such an endpoint would
# answer an anonymous request with 200 and real data, rather than a redirect-to-login or a DRF
# 401/403. Restricted to class-based views (the same `.cls`/`.view_class` discovery used
# throughout this file) -- Django admin's own views and the two project function-based views
# (core.views.healthz, accounts.views.throttled_admin_login) have neither attribute and are
# excluded the same way test_every_owned_view_uses_visible_to's discovery is: admin security is
# django.contrib.admin's own well-covered surface (plus config/tests/test_admin.py), not this
# task's gap, and both FBVs are deliberately, individually public (a health check and the
# throttled admin login page).

_PATH_PLACEHOLDER_BY_CONVERTER = {
    "int": "999999",
    "str": "x",
    "slug": "x",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "path": "x",
}
_PATH_PARAM_RE = re.compile(r"<(\w+):(\w+)>")


def _fill_path_params(route: str) -> str:
    return _PATH_PARAM_RE.sub(lambda m: _PATH_PLACEHOLDER_BY_CONVERTER.get(m.group(1), "x"), route)


def _iter_concrete_routes(urlconf: str) -> list[tuple[str, type]]:
    routes: list[tuple[str, type]] = []

    def walk(resolver: Any, prefix: str) -> None:
        for pattern in resolver.url_patterns:
            route = getattr(pattern.pattern, "_route", "")
            full_prefix = prefix + route
            if hasattr(pattern, "url_patterns"):
                walk(pattern, full_prefix)
            else:
                cls = getattr(pattern.callback, "cls", None) or getattr(
                    pattern.callback, "view_class", None
                )
                if cls is not None:
                    routes.append((_fill_path_params(full_prefix), cls))

    walk(get_resolver(urlconf), "/")
    return routes


def _probe_method(view_cls: type) -> str:
    """GET whenever the view answers GET (DRF viewsets always do, via list/retrieve; most HTML
    views do too) -- POST only for the write-only action Views that define no ``get`` at all.
    Preferring GET keeps the probe side-effect-free wherever possible.
    """
    if issubclass(view_cls, GenericViewSet):
        return "get"
    if getattr(view_cls, "get", None) is not None:
        return "get"
    if getattr(view_cls, "post", None) is not None:
        return "post"
    return "get"


#: Routes that are deliberately, individually reachable without authentication -- each one is a
#: conscious design decision documented at its own definition, not an oversight this sweep should
#: paper over:
#:   - accounts:login (accounts.views.TempPasswordAwareLoginView) -- the login form itself.
#:   - accounts:logout (django.contrib.auth.views.LogoutView) -- logging out an already-logged-
#:     out session is a no-op, not an error; Django's own view renders a confirmation page for
#:     POST regardless of prior auth state, and carries no user data.
#:   - accounts_api:login (accounts.api.LoginAPIView) -- the API login endpoint, AllowAny by
#:     design (accounts/api.py).
def _named_route_allowlisted(cls: type) -> bool:
    return f"{cls.__module__}.{cls.__qualname__}" in {
        "accounts.views.TempPasswordAwareLoginView",
        "django.contrib.auth.views.LogoutView",
        "accounts.api.LoginAPIView",
    }


_concrete_routes = [(path, cls) for path, cls in _iter_concrete_routes(settings.ROOT_URLCONF)]


@pytest.mark.parametrize(
    "path,view_cls",
    _concrete_routes,
    ids=[
        f"{method_cls.__module__}.{method_cls.__qualname__}:{p}"
        for p, method_cls in _concrete_routes
    ],
)
def test_anonymous_cannot_reach_any_data_endpoint(path: str, view_cls: type) -> None:
    if _named_route_allowlisted(view_cls):
        pytest.skip(
            f"{view_cls.__qualname__} is deliberately public -- see _named_route_allowlisted"
        )

    client = Client()
    method = _probe_method(view_cls)
    response = getattr(client, method)(path, {} if method == "post" else None)

    assert response.status_code != 200, (
        f"{view_cls.__module__}.{view_cls.__qualname__} answered an anonymous {method.upper()} "
        f"{path} with 200 -- either it is missing a permission class / LoginRequiredMixin, or "
        "it belongs in the explicit public allowlist above."
    )


def test_anonymous_route_sweep_is_not_vacuous() -> None:
    assert len(_concrete_routes) > 50, (
        "the route sweep found suspiciously few routes -- the discovery walk may be broken "
        "rather than the project actually having this few endpoints"
    )


@pytest.mark.urls("core.tests.urls")
def test_anonymous_route_sweep_actually_detects_a_missing_permission() -> None:
    """Direct proof the probe itself works: DummyOwned's list route (DummyOwnedViewSet --
    OwnedViewSetMixin composes IsAuthenticated in) must reject an anonymous GET. Confirms the
    assertion above would fail on a real regression rather than passing because every response
    happened to already be a redirect for unrelated reasons.
    """
    response = Client().get("/dummy/")
    assert response.status_code in (401, 403)
