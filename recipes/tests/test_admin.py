"""Recipe admin: the cycle guard on the third write path (09.4), plus the per-model N+1 and
search assertions from ``test-plan.md``.

Task 05's ``test-plan.md`` names this guard test ``test_guard_enforced_on_admin`` and defers
it here; task 09's ``test-plan.md`` names it ``test_cycle_guard_enforced_in_admin_inline``.
Both names are kept so either plan document reads as satisfied.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from recipes.admin import RecipeComponentInline
from recipes.models import Recipe
from recipes.services.graph import MAX_DEPTH

pytestmark = pytest.mark.django_db


def _management_form(total: int, initial: int = 0) -> dict:
    return {
        "components-TOTAL_FORMS": str(total),
        "components-INITIAL_FORMS": str(initial),
        "components-MIN_NUM_FORMS": "0",
        "components-MAX_NUM_FORMS": "1000",
    }


def _inline_formset(parent: Recipe, data: dict, user):
    request = RequestFactory().post("/")
    request.user = user
    inline = RecipeComponentInline(Recipe, AdminSite())
    formset_cls = inline.get_formset(request, obj=parent)
    return formset_cls(data, instance=parent)


@pytest.fixture
def superuser(user_factory):
    return user_factory(username="root", is_staff=True, is_superuser=True)


def test_cycle_guard_enforced_in_admin_inline(superuser, make_recipe, add_sub_recipe, cup):
    a = make_recipe("A")
    b = make_recipe("B")
    add_sub_recipe(b, a, 1, cup)  # B already contains A

    data = {
        **_management_form(1),
        "components-0-sub_recipe": str(b.pk),  # adding A -> B closes A -> B -> A
        "components-0-quantity": "1",
        "components-0-unit": str(cup.pk),
        "components-0-position": "0",
    }
    formset = _inline_formset(a, data, superuser)

    assert not formset.is_valid()
    assert "cycle" in str(formset.non_form_errors()).lower()
    a.refresh_from_db()
    assert not a.components.exists()


def test_sub_recipe_unit_scalability_enforced_in_admin_inline(superuser, make_recipe, cup, gram):
    """A component whose ``unit`` cannot be scaled to its ``sub_recipe``'s ``yield_unit``
    (mass called for, volume yielded) is refused on the inline formset path — otherwise the
    row 500s later in the flattener (09 rework, blocking #1). Same guard the serializer and
    the importer run, through the one shared helper.
    """
    parent = make_recipe("Parent")
    sub = make_recipe("Sub")  # yields cups (volume)

    data = {
        **_management_form(1),
        "components-0-sub_recipe": str(sub.pk),
        "components-0-quantity": "2",
        "components-0-unit": str(gram.pk),  # mass — cannot scale to a volume yield
        "components-0-position": "0",
    }
    formset = _inline_formset(parent, data, superuser)

    assert not formset.is_valid()
    assert "different things" in str(formset.errors).lower()
    parent.refresh_from_db()
    assert not parent.components.exists()


def test_sub_recipe_unit_scalability_enforced_in_standalone_component_admin(
    admin_client, make_recipe, cup, gram
):
    """The same guard on the standalone ``RecipeComponent`` add form (the fourth write path)."""
    parent = make_recipe("Parent")
    sub = make_recipe("Sub")  # yields cups (volume)

    url = reverse("admin:recipes_recipecomponent_add")
    response = admin_client.post(
        url,
        {
            "recipe": str(parent.pk),
            "sub_recipe": str(sub.pk),
            "quantity": "2",
            "unit": str(gram.pk),  # mass — cannot scale to a volume yield
            "position": "0",
            "note": "",
            "_save": "Save",
        },
    )

    assert response.status_code == 200  # re-rendered with the error, not a 302 redirect
    assert b"different things" in response.content
    assert not parent.components.exists()


def test_admin_inline_accepts_a_scalable_sub_recipe_unit(superuser, make_recipe, make_unit):
    """The mirror case: a compatible unit (both volume) on a sub-recipe component is fine."""
    parent = make_recipe("Parent")
    sub = make_recipe("Sub")  # yields cups
    tablespoon = make_unit("tablespoon")

    data = {
        **_management_form(1),
        "components-0-sub_recipe": str(sub.pk),
        "components-0-quantity": "3",
        "components-0-unit": str(tablespoon.pk),
        "components-0-position": "0",
    }
    formset = _inline_formset(parent, data, superuser)

    assert formset.is_valid(), (formset.errors, formset.non_form_errors())


def test_depth_guard_enforced_on_admin_add(superuser, alice, make_recipe, add_sub_recipe, cup):
    """The add form cannot close a cycle (nothing references a pk-less recipe yet), but it can
    still nest past ``MAX_DEPTH`` — the 09.1-09.4 review's blocking finding #2. A depth-only
    check must run in the ``parent.pk is None`` branch and raise ``DepthExceededError``.
    """
    chain = [make_recipe(f"Depth {i}") for i in range(MAX_DEPTH + 1)]
    for parent, child in zip(chain, chain[1:], strict=False):
        add_sub_recipe(parent, child, 1, cup)
    deep = chain[0]  # recipe_depth(deep) == MAX_DEPTH

    new_recipe = Recipe(
        name="Brand new",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=cup,
        owner=alice,
    )
    data = {
        **_management_form(1),
        "components-0-sub_recipe": str(deep.pk),  # 1 + MAX_DEPTH = MAX_DEPTH + 1 > MAX_DEPTH
        "components-0-quantity": "1",
        "components-0-unit": str(cup.pk),
        "components-0-position": "0",
    }
    formset = _inline_formset(new_recipe, data, superuser)

    assert not formset.is_valid()
    assert "exceed" in str(formset.non_form_errors()).lower()


def test_admin_add_accepts_sub_recipe_within_depth(superuser, alice, make_recipe, cup):
    """The mirror case: one level of nesting on a new recipe is fine — the depth-only check
    must not reject an ordinary sub-recipe.
    """
    sub = make_recipe("A sub")
    new_recipe = Recipe(
        name="Fresh", instructions="x", yield_quantity=Decimal("1"), yield_unit=cup, owner=alice
    )
    data = {
        **_management_form(1),
        "components-0-sub_recipe": str(sub.pk),
        "components-0-quantity": "1",
        "components-0-unit": str(cup.pk),
        "components-0-position": "0",
    }
    formset = _inline_formset(new_recipe, data, superuser)

    assert formset.is_valid(), (formset.errors, formset.non_form_errors())


def test_admin_inline_accepts_a_non_cyclic_sub_recipe(superuser, make_recipe, cup):
    a = make_recipe("A")
    b = make_recipe("B")

    data = {
        **_management_form(1),
        "components-0-sub_recipe": str(b.pk),
        "components-0-quantity": "1",
        "components-0-unit": str(cup.pk),
        "components-0-position": "0",
    }
    formset = _inline_formset(a, data, superuser)

    assert formset.is_valid(), (formset.errors, formset.non_form_errors())


def test_guard_enforced_on_admin(admin_client, make_recipe, add_sub_recipe, cup):
    """Full change-form POST through the admin — task 05's third write-path test."""
    a = make_recipe("A")
    b = make_recipe("B")
    add_sub_recipe(b, a, 1, cup)

    url = reverse("admin:recipes_recipe_change", args=[a.pk])
    payload = {
        "name": a.name,
        "description": "",
        "instructions": a.instructions,
        "yield_quantity": "4",
        "yield_unit": str(a.yield_unit_id),
        "prep_minutes": "0",
        "cook_minutes": "0",
        "role": a.role,
        "visibility": a.visibility,
        "source_url": "",
        **_management_form(1),
        "components-0-sub_recipe": str(b.pk),
        "components-0-quantity": "1",
        "components-0-unit": str(cup.pk),
        "components-0-position": "0",
        "components-0-note": "",
        "_save": "Save",
    }
    response = admin_client.post(url, payload)

    assert response.status_code == 200  # re-rendered with errors, not a 302 redirect
    assert b"Recipe cycle detected" in response.content
    a.refresh_from_db()
    assert not a.components.filter(sub_recipe=b).exists()


def test_standalone_component_admin_rejects_cycle(admin_client, make_recipe, add_sub_recipe, cup):
    """The standalone ``RecipeComponent`` add form is a fourth ``sub_recipe`` write path
    (09 rework, blocking #1). Posting an edge that closes a cycle must be refused.
    """
    a = make_recipe("A")
    b = make_recipe("B")
    add_sub_recipe(b, a, 1, cup)  # B already contains A

    url = reverse("admin:recipes_recipecomponent_add")
    response = admin_client.post(
        url,
        {
            "recipe": str(a.pk),
            "sub_recipe": str(b.pk),  # adding A -> B closes A -> B -> A
            "quantity": "1",
            "unit": str(cup.pk),
            "position": "0",
            "note": "",
            "_save": "Save",
        },
    )

    assert response.status_code == 200  # re-rendered with the error, not a 302 redirect
    assert b"cycle" in response.content.lower()
    assert not a.components.filter(sub_recipe=b).exists()


def test_standalone_component_admin_rejects_over_deep(
    admin_client, make_recipe, add_sub_recipe, cup
):
    """The same path must also reject an edge that would nest past ``MAX_DEPTH``."""
    chain = [make_recipe(f"Deep {i}") for i in range(MAX_DEPTH + 1)]
    for parent, child in zip(chain, chain[1:], strict=False):
        add_sub_recipe(parent, child, 1, cup)
    top = make_recipe("Top")  # recipe_depth(chain[0]) == MAX_DEPTH

    url = reverse("admin:recipes_recipecomponent_add")
    response = admin_client.post(
        url,
        {
            "recipe": str(top.pk),
            "sub_recipe": str(chain[0].pk),  # 1 + MAX_DEPTH > MAX_DEPTH
            "quantity": "1",
            "unit": str(cup.pk),
            "position": "0",
            "note": "",
            "_save": "Save",
        },
    )

    assert response.status_code == 200
    assert b"exceed" in response.content
    assert not top.components.exists()


def test_standalone_component_admin_change_rejects_cycle(
    admin_client, make_recipe, add_sub_recipe, cup
):
    """Editing an existing component's ``sub_recipe`` through the standalone change form is
    guarded too.
    """
    a = make_recipe("A")
    b = make_recipe("B")
    c = make_recipe("C")
    add_sub_recipe(b, a, 1, cup)  # B contains A
    comp = add_sub_recipe(a, c, 1, cup)  # A contains C — harmless

    url = reverse("admin:recipes_recipecomponent_change", args=[comp.pk])
    response = admin_client.post(
        url,
        {
            "recipe": str(a.pk),
            "sub_recipe": str(b.pk),  # C -> B; A -> B -> A closes a cycle
            "quantity": "1",
            "unit": str(cup.pk),
            "position": "0",
            "note": "",
            "_save": "Save",
        },
    )

    assert response.status_code == 200
    assert b"cycle" in response.content.lower()
    comp.refresh_from_db()
    assert comp.sub_recipe_id == c.pk


def test_standalone_component_admin_accepts_a_non_cyclic_sub_recipe(admin_client, make_recipe, cup):
    a = make_recipe("A")
    b = make_recipe("B")

    url = reverse("admin:recipes_recipecomponent_add")
    response = admin_client.post(
        url,
        {
            "recipe": str(a.pk),
            "sub_recipe": str(b.pk),
            "quantity": "1",
            "unit": str(cup.pk),
            "position": "0",
            "note": "",
            "_save": "Save",
        },
    )

    assert response.status_code == 302  # saved, redirect to the changelist
    assert a.components.filter(sub_recipe=b).exists()


def _changelist_query_count(client, url: str) -> int:
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    assert response.status_code == 200
    return len(ctx.captured_queries)


def test_changelist_query_count_bounded(client, superuser, alice, cup, make_recipe):
    """A 50-row changelist fires the same number of queries as a 5-row one — no N+1 from the
    ``owner`` / ``yield_unit`` columns (``list_select_related``).
    """
    client.force_login(superuser)
    url = reverse("admin:recipes_recipe_changelist")

    for i in range(5):
        make_recipe(f"Recipe {i:03d}", owner=alice)
    baseline = _changelist_query_count(client, url)

    for i in range(5, 50):
        make_recipe(f"Recipe {i:03d}", owner=alice)
    scaled = _changelist_query_count(client, url)

    assert scaled == baseline, f"changelist N+1: {baseline} -> {scaled} queries"


def test_search_works(client, superuser, alice, make_recipe):
    client.force_login(superuser)
    make_recipe("Findable Pancakes", owner=alice)
    make_recipe("Unrelated Casserole", owner=alice)
    url = reverse("admin:recipes_recipe_changelist")

    response = client.get(url, {"q": "Pancakes"})

    assert response.status_code == 200
    assert b"Findable Pancakes" in response.content
    assert b"Unrelated Casserole" not in response.content


def test_admin_recipe_stats_changelist_search(client, superuser, alice, make_recipe):
    """A ``RecipeStats`` search spans the ``user`` and ``recipe`` FKs — proves the
    ``search_fields`` traversal resolves.
    """
    from recipes.models import RecipeStats

    recipe = make_recipe("Soup", owner=alice)
    RecipeStats.objects.create(user=alice, recipe=recipe, rating=4)
    client.force_login(superuser)

    response = client.get(reverse("admin:recipes_recipestats_changelist"), {"q": "Soup"})

    assert response.status_code == 200
    assert b"Soup" in response.content
