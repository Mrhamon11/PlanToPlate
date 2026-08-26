"""Plan/03-Ownership-And-Sharing/test-plan.md, "Regression guard — core/tests/test_conventions.py"
(03.8a / NB3).

The 03.5-03.8 review took two rounds to catch, by eye, a viewset composing its permissions
wrong. Tasks 04-08 are about to add six more viewsets over real ``OwnedModel`` subclasses —
nothing else in the suite would notice if one of them forgot ``OwnedViewSetMixin`` (and so
never routes through ``.visible_to()`` at all) or forgot to declare ``share_dependencies()``/
``copy_children()`` on a model that actually has children to cascade through. These two tests
are that watch.

Each check function below is exercised twice: once as the real regression guard (walking the
URLconf-reachable viewsets, and the real app/model registry), and once against a deliberately
broken stand-in built inside the test itself, so a green "no offenders" result can't be
explained by the detection logic silently matching nothing.
"""

from __future__ import annotations

import inspect

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.urls import get_resolver
from rest_framework import viewsets as drf_viewsets
from rest_framework.viewsets import GenericViewSet

from core.models import OwnedModel
from core.viewsets import OwnedViewSetMixin

pytestmark = pytest.mark.django_db

# core/models.py's OwnedModel.copied_from declares related_name="copies" -- every concrete
# subclass therefore has a self-referential *reverse* relation of that name, which points back
# at an OwnedModel (itself) but is never a "this model contains other owned objects" signal.
# Named explicitly here (rather than derived) since OwnedModel is abstract and never carries its
# own reverse relations for _meta.get_fields() to enumerate.
_COPIED_FROM_REVERSE_ACCESSOR = "copies"

_INHERITED_OWNED_MODEL_FIELD_NAMES = {field.name for field in OwnedModel._meta.get_fields()} | {
    _COPIED_FROM_REVERSE_ACCESSOR
}


# --- test_all_owned_viewsets_use_visible_to ---------------------------------------------------


def _model_for_viewset(viewset_cls: type[GenericViewSet]) -> type | None:
    """The model a viewset serves, read the same two ways DRF itself derives one: an explicit
    ``queryset`` first, falling back to the serializer's ``Meta.model``.
    """
    queryset = getattr(viewset_cls, "queryset", None)
    if queryset is not None:
        return queryset.model
    serializer_class = getattr(viewset_cls, "serializer_class", None)
    meta = getattr(serializer_class, "Meta", None) if serializer_class else None
    return getattr(meta, "model", None)


def _iter_view_classes_from_urlconf(urlconf: str) -> list[type]:
    """Every view class reachable from ``urlconf``, found by walking the resolved URL pattern
    tree and reading ``pattern.callback.cls`` — the attribute both ``APIView.as_view()`` and
    ``ViewSetMixin.as_view()`` set on the returned view function specifically so tooling (DRF's
    own breadcrumb generation, drf-spectacular, and this check) can recover the original class
    from a resolved URL.

    This is "every registered viewset" as test-plan.md actually means it: immune to which
    module a viewset happens to be defined in (``<app>/viewsets.py``, ``<app>/api.py``, or
    anywhere else), unlike scanning app modules by a guessed name — the mistake this guard used
    to make, which left it blind to ``accounts/api.py`` and to the ``catalog/api.py``/
    ``recipes/api.py`` names tasks 04/05 actually use.
    """
    classes: list[type] = []
    stack = [get_resolver(urlconf)]
    while stack:
        current = stack.pop()
        for pattern in current.url_patterns:
            if hasattr(pattern, "url_patterns"):
                stack.append(pattern)
            else:
                cls = getattr(pattern.callback, "cls", None)
                if cls is not None:
                    classes.append(cls)
    return classes


def _all_registered_viewset_classes() -> list[type[GenericViewSet]]:
    """Every DRF viewset class reachable from the project's real root URLconf
    (``settings.ROOT_URLCONF`` — ``config.urls``, what production actually serves) plus
    ``core.tests.urls`` (the throwaway fixture router this app's own suite registers under test
    settings, per ``core/tests/apps.py``).

    The second pass is what keeps this check's own non-vacuousness independent of a real
    domain viewset existing yet — today (task 03) ``config.urls`` has none at all, since task 04
    is the first task to add one. Deduped by class identity, since a router registers the same
    viewset class under several patterns (list, detail, each ``@action``).
    """
    seen: dict[int, type[GenericViewSet]] = {}
    for urlconf in (settings.ROOT_URLCONF, "core.tests.urls"):
        for cls in _iter_view_classes_from_urlconf(urlconf):
            if issubclass(cls, GenericViewSet) and cls is not GenericViewSet:
                seen[id(cls)] = cls
    return list(seen.values())


def _owned_model_viewsets() -> list[type[GenericViewSet]]:
    """Every registered viewset (per ``_all_registered_viewset_classes``) whose model is a
    concrete ``OwnedModel`` subclass.
    """
    found: list[type[GenericViewSet]] = []
    for viewset_cls in _all_registered_viewset_classes():
        model = _model_for_viewset(viewset_cls)
        if model is not None and issubclass(model, OwnedModel):
            found.append(viewset_cls)
    return found


def _routes_through_visible_to(viewset_cls: type[GenericViewSet]) -> bool:
    """True if ``get_queryset`` is either literally ``OwnedViewSetMixin.get_queryset`` (the
    common case) or a deliberate override whose source still calls ``super().get_queryset()``
    — the one documented way (``core/README.md``, "Viewset") to add extra filtering without
    dropping the ``visible_to()`` scoping ``OwnedViewSetMixin`` provides.

    Anything else — an override that doesn't delegate at all, the exact "add a filter in a
    hurry" mistake ``core/README.md`` warns against — fails this check even though
    ``issubclass(vs, OwnedViewSetMixin)`` is still True. Checking only the MRO, as this guard
    used to, would miss it entirely.
    """
    if viewset_cls.get_queryset is OwnedViewSetMixin.get_queryset:
        return True
    try:
        source = inspect.getsource(viewset_cls.get_queryset)
    except (OSError, TypeError):
        return False
    return "super(" in source and "get_queryset" in source


def _viewsets_missing_owned_mixin(
    viewset_classes: list[type[GenericViewSet]],
) -> list[type[GenericViewSet]]:
    offenders: list[type[GenericViewSet]] = []
    for vs in viewset_classes:
        if not issubclass(vs, OwnedViewSetMixin):
            offenders.append(vs)
        elif not _routes_through_visible_to(vs):
            offenders.append(vs)
    return offenders


def test_all_owned_viewsets_use_visible_to():
    """Every registered viewset whose model subclasses ``OwnedModel`` must mix in
    ``OwnedViewSetMixin`` *and* actually route ``get_queryset()`` through it. A viewset over an
    owned model without either has no visibility filtering at all: every row, to everyone.
    """
    owned_viewsets = _owned_model_viewsets()

    assert owned_viewsets, (
        "no viewset over an OwnedModel was found anywhere in the URLconf — this test would "
        "pass vacuously if core.tests.viewsets.DummyOwnedViewSet/DummyNodeViewSet ever stopped "
        "being reachable from core.tests.urls"
    )

    offenders = _viewsets_missing_owned_mixin(owned_viewsets)

    assert offenders == [], (
        "viewset(s) serving an OwnedModel without OwnedViewSetMixin, or without routing "
        f"get_queryset() through it: {[f'{vs.__module__}.{vs.__qualname__}' for vs in offenders]}"
    )


def test_owned_viewset_missing_mixin_is_actually_detected():
    """Proves the detection logic above is not vacuous by construction: a viewset that serves
    an OwnedModel but omits ``OwnedViewSetMixin`` entirely must be flagged by the same functions
    the real guard uses.
    """
    from core.tests.models import DummyOwned
    from core.tests.serializers import DummySerializer

    class RogueViewSet(drf_viewsets.ModelViewSet):
        queryset = DummyOwned.objects.all()
        serializer_class = DummySerializer

    assert _model_for_viewset(RogueViewSet) is DummyOwned
    assert _viewsets_missing_owned_mixin([RogueViewSet]) == [RogueViewSet]


def test_viewset_that_overrides_get_queryset_without_super_is_detected():
    """The exact mistake ``core/README.md`` warns against: mixing in ``OwnedViewSetMixin`` and
    then writing a ``get_queryset()`` that never calls ``super()``, silently dropping
    ``visible_to()`` scoping even though ``issubclass(vs, OwnedViewSetMixin)`` is still True.
    A guard that only checked the MRO would miss this.
    """
    from core.tests.models import DummyOwned
    from core.tests.serializers import DummySerializer

    class CarelessViewSet(OwnedViewSetMixin, drf_viewsets.ModelViewSet):
        queryset = DummyOwned.objects.all()
        serializer_class = DummySerializer

        def get_queryset(self):
            return DummyOwned.objects.all()

    assert issubclass(CarelessViewSet, OwnedViewSetMixin)
    assert _viewsets_missing_owned_mixin([CarelessViewSet]) == [CarelessViewSet]


def test_viewset_that_extends_get_queryset_via_super_is_not_a_false_positive():
    """The documented pattern (``core/README.md``, "Viewset") — narrowing further on top of
    ``super().get_queryset()`` — must not be flagged.
    """
    from core.tests.models import DummyOwned
    from core.tests.serializers import DummySerializer

    class NarrowingViewSet(OwnedViewSetMixin, drf_viewsets.ModelViewSet):
        queryset = DummyOwned.objects.all()
        serializer_class = DummySerializer

        def get_queryset(self):
            return super().get_queryset().filter(name="only-this-one")

    assert _viewsets_missing_owned_mixin([NarrowingViewSet]) == []


# --- test_all_owned_models_declare_hooks --------------------------------------------------------


def _is_owned_model(model: type | None) -> bool:
    return (
        model is not None
        and inspect.isclass(model)
        and issubclass(model, OwnedModel)
        and model is not OwnedModel
    )


def _declares_relation_to_owned_model(model: type[OwnedModel]) -> bool:
    """True if ``model`` can reach another ``OwnedModel`` subclass: as its own forward FK/M2M,
    as the reverse side of one, or one hop further through a plain (non-owned) join model's own
    forward relation. Fields ``OwnedModel`` itself declares (``owner``, ``shared_with``,
    ``copied_from`` and its ``copies`` reverse accessor) are excluded — none of those make a
    model a *container* of other owned objects.

    The one-hop-through-a-join-model branch is what actually matters: every planned container
    (``Recipe``, ``Dish``, ``RecipeBook``) reaches its children only in reverse, through a plain
    model that is not itself an ``OwnedModel`` (``RecipeComponent``, ``DishComponent``,
    ``RecipeBookEntry`` — see ``Plan/05-Recipes/design.md``, ``Plan/06-.../design.md``). A check
    that only looked at ``model``'s own forward fields (the previous shape of this function)
    would never see this and would let such a container through with no
    ``share_dependencies()``/``copy_children()`` override at all — proven directly by
    ``core.tests.models.DummyContainer``/``DummyComponent`` below, which reproduce that exact
    shape.

    This walk is deliberately symmetric, and that is a known, accepted over-approximation: a
    join model with two different ``OwnedModel`` parents (``RecipeComponent.recipe`` ->
    ``Recipe``, ``RecipeComponent.ingredient`` -> ``Ingredient``) looks identical from either
    parent's side, so this function also returns ``True`` for the *leaf* (``Ingredient``), not
    only the real container (``Recipe``). It cannot be narrowed to fix that without also losing
    real containers reached the same way — see ``core.tests.models.DummyJoinedLeaf`` /
    ``DummyJoinedContainer`` below, and ``_owned_models_missing_hooks()``'s
    ``contains_owned_children`` opt-out, which is where that ambiguity actually gets resolved.
    """
    for field in model._meta.get_fields():
        if field.name in _INHERITED_OWNED_MODEL_FIELD_NAMES:
            continue
        if not field.is_relation:
            continue
        related_model = getattr(field, "related_model", None)
        if related_model is None:
            continue
        if _is_owned_model(related_model):
            return True
        if field.concrete:
            continue
        for join_field in related_model._meta.get_fields():
            if not join_field.concrete or not join_field.is_relation:
                continue
            if _is_owned_model(getattr(join_field, "related_model", None)):
                return True
    return False


def _owned_models_missing_hooks() -> list[type[OwnedModel]]:
    """Every ``OwnedModel`` subclass that must override ``share_dependencies()``/
    ``copy_children()`` but has not.

    ``model.contains_owned_children`` (``core/models.py``) is consulted before the heuristic,
    not after, and can override it in either direction:

    - ``False`` exempts the model unconditionally — the escape hatch for the one shape
      ``_declares_relation_to_owned_model`` genuinely cannot resolve on its own: a leaf reached
      through the *other* FK of a two-parent join model that also joins a real container to its
      children. Skipping the reverse relation's own back-reference does not fix this (the
      join model's *other* forward FK, pointing at the real container, remains) — see the
      docstring above and ``Plan/03-Ownership-And-Sharing/.review-findings.md``'s iteration-3
      finding 2. Declaring this is a deliberate, reviewable, greppable statement ("I decided
      this model has no owned children"), unlike a no-op hook override, which reads
      identically whether the author investigated or just wanted the guard to stop failing.
    - ``True`` forces the model to be checked regardless of what the heuristic sees, for the
      rare case a container's only relation to its children is structured in a way the walk
      above does not recognise.
    - ``None`` (the default — nearly every model) defers entirely to the heuristic, exactly as
      before this opt-out existed.
    """
    offenders: list[type[OwnedModel]] = []
    for model in django_apps.get_models():
        if not issubclass(model, OwnedModel) or model is OwnedModel:
            continue
        declared = model.contains_owned_children
        if declared is False:
            continue
        if declared is None and not _declares_relation_to_owned_model(model):
            continue
        share_overridden = model.share_dependencies is not OwnedModel.share_dependencies
        copy_overridden = model.copy_children is not OwnedModel.copy_children
        if not (share_overridden and copy_overridden):
            offenders.append(model)
    return offenders


def test_all_owned_models_declare_hooks():
    """Every ``OwnedModel`` subclass with a relation to another ``OwnedModel`` — directly, or
    through a reverse relation into a plain join model — must override both
    ``share_dependencies()`` and ``copy_children()``. The default (empty) implementation is
    correct for a leaf model, but silently wrong for a container — it would make the sharing
    cascade and the copy service treat a real parent/child relationship as if it didn't exist,
    leaving a shared or copied container hollow with no error at all.
    """
    offenders = _owned_models_missing_hooks()

    assert offenders == [], (
        "OwnedModel subclass(es) with a relation to another OwnedModel but missing "
        f"share_dependencies()/copy_children() overrides: {[m.__name__ for m in offenders]}"
    )


def test_relation_model_missing_hooks_is_actually_detected(monkeypatch):
    """Proves the check above is not vacuous: temporarily reverting one of the fixture models
    that genuinely has a *forward* relation to another OwnedModel
    (``core.tests.models.DummyNode.depends_on``) back to the inherited default must be caught.
    """
    from core.tests.models import DummyNode

    assert _declares_relation_to_owned_model(DummyNode) is True
    monkeypatch.setattr(DummyNode, "share_dependencies", OwnedModel.share_dependencies)

    offenders = _owned_models_missing_hooks()

    assert DummyNode in offenders


def test_container_reaching_children_through_a_join_model_is_detected(monkeypatch):
    """Proves the guard is not vacuous against the actual task-05+ container shape either: a
    parent that reaches its children only through the *reverse* side of a plain join model
    (``core.tests.models.DummyContainer`` / ``DummyComponent``), not only against DummyNode's
    forward self-M2M. Reverting ``share_dependencies()`` to the inherited default must be caught
    the same way.
    """
    from core.tests.models import DummyContainer

    assert _declares_relation_to_owned_model(DummyContainer) is True
    monkeypatch.setattr(DummyContainer, "share_dependencies", OwnedModel.share_dependencies)

    offenders = _owned_models_missing_hooks()

    assert DummyContainer in offenders


def test_leaf_model_with_no_owned_relation_is_not_flagged():
    """Non-vacuousness in the other direction: ``DummyOwned`` has no relation to another
    ``OwnedModel`` at all — not even through a join model — so it must never be reported as
    needing hooks, regardless of whether it happens to override them.
    """
    from core.tests.models import DummyOwned

    assert _declares_relation_to_owned_model(DummyOwned) is False


# --- the join-model false positive (iteration-3 review blocking finding 2) ---------------------
# _declares_relation_to_owned_model's join-model branch is symmetric: it cannot tell a real
# container (Recipe, reached via RecipeComponent.recipe) apart from a genuine leaf reached
# through the *same* join model's other FK (Ingredient, via RecipeComponent.ingredient) --
# DummyContainer/DummyComponent above doesn't exercise this, since both of DummyComponent's FKs
# point at DummyContainer itself. DummyJoinedContainer/DummyJoinedLeaf/DummyJoinedComponent do.


def test_join_model_heuristic_still_flags_the_leaf_half_by_itself():
    """Documents the false positive directly: with no opt-out consulted, the raw relation-walk
    genuinely cannot distinguish DummyJoinedLeaf (a leaf) from DummyJoinedContainer (a real
    container) — both come back True. This is why ``contains_owned_children`` exists; it is not
    a fix to this function.
    """
    from core.tests.models import DummyJoinedContainer, DummyJoinedLeaf

    assert _declares_relation_to_owned_model(DummyJoinedContainer) is True
    assert _declares_relation_to_owned_model(DummyJoinedLeaf) is True


def test_leaf_reached_through_two_parent_join_model_is_not_flagged_once_opted_out():
    """The actual fix: ``DummyJoinedLeaf`` declares ``contains_owned_children = False``
    (``core/tests/models.py``), so ``_owned_models_missing_hooks()`` must exempt it even though
    the heuristic above still (correctly, given its limits) says it looks like a container.
    """
    from core.tests.models import DummyJoinedLeaf

    assert DummyJoinedLeaf not in _owned_models_missing_hooks()


def test_leaf_opt_out_is_load_bearing_not_vacuous(monkeypatch):
    """Proves the opt-out above is actually doing the work, not merely coincidental: with
    ``contains_owned_children`` reverted to the inherited default (``None``), the same
    ``DummyJoinedLeaf`` — with no hooks overridden, same as it ships — must be flagged.
    """
    from core.tests.models import DummyJoinedLeaf

    monkeypatch.setattr(DummyJoinedLeaf, "contains_owned_children", None)

    assert DummyJoinedLeaf in _owned_models_missing_hooks()


def test_container_reaching_children_through_two_parent_join_model_is_still_detected(monkeypatch):
    """The opt-out must not blunt detection of the real container sharing the same join model:
    ``DummyJoinedContainer`` overrides both hooks by default, and reverting one must still be
    caught, exactly as ``test_container_reaching_children_through_a_join_model_is_detected``
    proves for the single-parent-model shape above.
    """
    from core.tests.models import DummyJoinedContainer

    monkeypatch.setattr(DummyJoinedContainer, "share_dependencies", OwnedModel.share_dependencies)

    assert DummyJoinedContainer in _owned_models_missing_hooks()
