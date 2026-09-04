"""HTML (HTMX) screens for recipes (``Plan/05-Recipes/test-plan.md``, "UI").

The form-specific rows (``test_form_*`` / ``test_htmx_add_component_row``) belong to 05.12 and
land with it. This file covers the list, the detail page, the scale control, the sub-recipe
expander and the print view — plus the instruction-escaping check the security test plan
defers to "the HTML screens".
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from core.models import Visibility
from recipes.models import Recipe, RecipeComponent, RecipeStats

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in(client, user_factory):
    user = user_factory(username="me")
    client.force_login(user)
    return client, user


# --- list ----------------------------------------------------------------------------------


def test_recipe_list_requires_login(client):
    response = client.get(reverse("recipes:recipe-list"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_list_shows_only_visible(logged_in, alice, make_recipe):
    client, me = logged_in
    make_recipe(name="My Weeknight Pasta", owner=me, visibility=Visibility.PRIVATE)
    make_recipe(name="Alice Secret Roast", owner=alice, visibility=Visibility.PRIVATE)

    content = client.get(reverse("recipes:recipe-list")).content.decode()

    assert "My Weeknight Pasta" in content
    assert "Alice Secret Roast" not in content


def test_list_htmx_search_returns_fragment(logged_in, make_recipe):
    client, me = logged_in
    make_recipe(name="Carbonara", owner=me, visibility=Visibility.PRIVATE)
    make_recipe(name="Minestrone", owner=me, visibility=Visibility.PRIVATE)

    response = client.get(reverse("recipes:recipe-list") + "?search=carb", HTTP_HX_REQUEST="true")

    content = response.content.decode()
    assert response.status_code == 200
    assert "<html" not in content
    assert "Carbonara" in content
    assert "Minestrone" not in content


def test_list_favorite_filter_uses_requesters_stats(logged_in, alice, make_recipe):
    client, me = logged_in
    fav = make_recipe(name="My Favourite", owner=me, visibility=Visibility.PRIVATE)
    plain = make_recipe(name="Just Fine", owner=me, visibility=Visibility.PRIVATE)
    RecipeStats.objects.create(user=me, recipe=fav, is_favorite=True)
    # Alice favouriting `plain` must not make it show up in my favourites filter.
    RecipeStats.objects.create(user=alice, recipe=plain, is_favorite=True)

    content = client.get(reverse("recipes:recipe-list") + "?favorite=1").content.decode()

    assert "My Favourite" in content
    assert "Just Fine" not in content


def test_list_role_filter_narrows(logged_in, make_recipe):
    client, me = logged_in
    make_recipe(name="Roast Chicken", owner=me, role="PROTEIN", visibility=Visibility.PRIVATE)
    make_recipe(name="Rice Pilaf", owner=me, role="CARB", visibility=Visibility.PRIVATE)

    content = client.get(reverse("recipes:recipe-list") + "?role=PROTEIN").content.decode()

    assert "Roast Chicken" in content
    assert "Rice Pilaf" not in content


def test_list_card_shows_viewers_rating_and_favourite(logged_in, make_recipe):
    client, me = logged_in
    recipe = make_recipe(name="Katsu Curry", owner=me, visibility=Visibility.PRIVATE)
    RecipeStats.objects.create(user=me, recipe=recipe, rating=3, is_favorite=True)

    content = client.get(reverse("recipes:recipe-list")).content.decode()

    assert "Your rating: 3 out of 5" in content
    assert "★ Favourite" in content


# --- detail --------------------------------------------------------------------------------


def test_detail_404_for_invisible(logged_in, alice, make_recipe):
    client, _me = logged_in
    recipe = make_recipe(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)

    assert client.get(reverse("recipes:recipe-detail", args=[recipe.pk])).status_code == 404


def test_detail_renders_for_owner(logged_in, make_recipe, make_ingredient, add_ingredient, gram):
    client, me = logged_in
    recipe = make_recipe(name="Shakshuka", owner=me, visibility=Visibility.PRIVATE)
    add_ingredient(recipe, make_ingredient("Eggs", owner=me), 4, gram)

    response = client.get(reverse("recipes:recipe-detail", args=[recipe.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Shakshuka" in content
    assert "Eggs" in content
    assert reverse("recipes:recipe-print", args=[recipe.pk]) in content


def test_instructions_are_escaped(logged_in, make_recipe):
    client, me = logged_in
    recipe = make_recipe(
        name="Sneaky",
        owner=me,
        visibility=Visibility.PRIVATE,
        instructions="<script>alert('xss')</script>",
    )

    content = client.get(reverse("recipes:recipe-detail", args=[recipe.pk])).content.decode()

    assert "<script>alert(" not in content
    assert "&lt;script&gt;" in content


# --- scale control ------------------------------------------------------------------------


def test_htmx_scale_rerenders_quantities(
    logged_in, make_recipe, make_ingredient, add_ingredient, gram
):
    client, me = logged_in
    recipe = make_recipe(name="Soup", owner=me, visibility=Visibility.PRIVATE)
    add_ingredient(recipe, make_ingredient("Stock", owner=me), 500, gram)

    response = client.get(
        reverse("recipes:recipe-scale", args=[recipe.pk]) + "?factor=3",
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "<html" not in content
    assert "1500" in content  # 500 g * 3
    # nothing persisted
    assert RecipeComponent.objects.get(recipe=recipe).quantity == Decimal("500.000")


def test_scale_bad_factor_falls_back_to_unscaled(
    logged_in, make_recipe, make_ingredient, add_ingredient, gram
):
    client, me = logged_in
    recipe = make_recipe(name="Soup", owner=me, visibility=Visibility.PRIVATE)
    add_ingredient(recipe, make_ingredient("Stock", owner=me), 500, gram)

    response = client.get(
        reverse("recipes:recipe-scale", args=[recipe.pk]) + "?factor=nonsense",
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert "500" in response.content.decode()


def test_scale_invisible_recipe_404s(logged_in, alice, make_recipe):
    client, _me = logged_in
    recipe = make_recipe(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)

    assert client.get(reverse("recipes:recipe-scale", args=[recipe.pk])).status_code == 404


# --- sub-recipe expander -----------------------------------------------------------------


def test_subrecipe_expander_returns_fragment(
    logged_in, make_recipe, make_ingredient, add_ingredient, add_sub_recipe, gram, cup
):
    client, me = logged_in
    marinara = make_recipe(name="Marinara", owner=me, visibility=Visibility.PRIVATE)
    add_ingredient(marinara, make_ingredient("Crushed Tomatoes", owner=me), 800, gram)
    parm = make_recipe(name="Chicken Parm", owner=me, visibility=Visibility.PRIVATE)
    component = add_sub_recipe(parm, marinara, 1, cup)

    response = client.get(
        reverse("recipes:recipe-component-expand", args=[parm.pk, component.pk]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "<html" not in content
    assert "Crushed Tomatoes" in content


def test_subrecipe_expander_degrades_when_subrecipe_invisible(
    logged_in, alice, make_recipe, make_ingredient, add_ingredient, add_sub_recipe, gram, cup
):
    """Defence in depth: a component pointing at a sub-recipe the viewer cannot see shows only
    the name, never its ingredients, and never 500s (design.md, "Edge cases").
    """
    client, me = logged_in
    secret = make_recipe(name="Alice Secret Base", owner=alice, visibility=Visibility.PRIVATE)
    add_ingredient(secret, make_ingredient("Truffle Oil", owner=alice), 10, gram)
    # A recipe I can see whose component points at Alice's private sub-recipe (would only
    # happen through a share-cascade bug — the row still exists, the visibility does not).
    mine = make_recipe(name="My Dish", owner=me, visibility=Visibility.PRIVATE)
    component = add_sub_recipe(mine, secret, 1, cup)

    response = client.get(
        reverse("recipes:recipe-component-expand", args=[mine.pk, component.pk]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Truffle Oil" not in content
    assert "not available to you" in content


# --- print view -------------------------------------------------------------------------


def test_print_view_renders(logged_in, make_recipe, make_ingredient, add_ingredient, gram):
    client, me = logged_in
    recipe = make_recipe(name="Focaccia", owner=me, visibility=Visibility.PRIVATE)
    add_ingredient(recipe, make_ingredient("Flour", owner=me), 500, gram)

    response = client.get(reverse("recipes:recipe-print", args=[recipe.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Focaccia" in content
    assert "Flour" in content
    assert "print.css" in content


def test_print_view_404_for_invisible(logged_in, alice, make_recipe):
    client, _me = logged_in
    recipe = make_recipe(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)

    assert client.get(reverse("recipes:recipe-print", args=[recipe.pk])).status_code == 404


def test_print_view_inlines_subrecipe_ingredients(
    logged_in, make_recipe, make_ingredient, add_ingredient, add_sub_recipe, gram, cup
):
    """A sub-recipe on the print page lists its own ingredients, not just its name — you cannot
    shop or cook from "1 cup Marinara" alone (dev-test finding; design.md, "People cook from
    paper").
    """
    client, me = logged_in
    marinara = make_recipe(name="Marinara", owner=me, visibility=Visibility.PRIVATE)
    add_ingredient(marinara, make_ingredient("Crushed Tomatoes", owner=me), 800, gram)
    parm = make_recipe(name="Chicken Parm", owner=me, visibility=Visibility.PRIVATE)
    add_ingredient(parm, make_ingredient("Chicken Breast", owner=me), 600, gram)
    add_sub_recipe(parm, marinara, 1, cup)

    content = client.get(reverse("recipes:recipe-print", args=[parm.pk])).content.decode()

    assert "Marinara" in content
    assert "Crushed Tomatoes" in content  # the sub-recipe's own ingredient, inlined
    assert content.count('class="print-ingredients"') >= 2  # the nested list is rendered


# --- stats widgets --------------------------------------------------------------------


def test_made_button_increments_requesters_stats(logged_in, make_recipe):
    client, me = logged_in
    recipe = make_recipe(name="Chili", owner=me, visibility=Visibility.PRIVATE)

    response = client.post(reverse("recipes:recipe-made", args=[recipe.pk]))

    assert response.status_code == 302
    assert RecipeStats.objects.get(user=me, recipe=recipe).times_made == 1


def test_favorite_toggle(logged_in, make_recipe):
    client, me = logged_in
    recipe = make_recipe(name="Dal", owner=me, visibility=Visibility.PRIVATE)

    client.post(reverse("recipes:recipe-favorite", args=[recipe.pk]))
    assert RecipeStats.objects.get(user=me, recipe=recipe).is_favorite is True

    client.post(reverse("recipes:recipe-favorite", args=[recipe.pk]))
    assert RecipeStats.objects.get(user=me, recipe=recipe).is_favorite is False


def test_rating_widget_sets_and_clears(logged_in, make_recipe):
    client, me = logged_in
    recipe = make_recipe(name="Congee", owner=me, visibility=Visibility.PRIVATE)

    client.post(reverse("recipes:recipe-rate", args=[recipe.pk]), {"rating": "4"})
    assert RecipeStats.objects.get(user=me, recipe=recipe).rating == 4

    client.post(reverse("recipes:recipe-rate", args=[recipe.pk]), {"rating": "0"})
    assert RecipeStats.objects.get(user=me, recipe=recipe).rating is None


def test_rating_widget_rejects_out_of_range(logged_in, make_recipe):
    client, me = logged_in
    recipe = make_recipe(name="Ramen", owner=me, visibility=Visibility.PRIVATE)

    client.post(reverse("recipes:recipe-rate", args=[recipe.pk]), {"rating": "9"})

    assert not RecipeStats.objects.filter(user=me, recipe=recipe, rating=9).exists()


def test_stats_widgets_404_on_invisible_recipe(logged_in, alice, make_recipe):
    client, _me = logged_in
    recipe = make_recipe(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)

    assert client.post(reverse("recipes:recipe-made", args=[recipe.pk])).status_code == 404
    assert client.post(reverse("recipes:recipe-favorite", args=[recipe.pk])).status_code == 404


# --- share / copy controls ----------------------------------------------------------


def test_detail_shows_copy_button_for_non_owner(logged_in, alice, make_recipe):
    client, _me = logged_in
    recipe = make_recipe(name="Alice Public Stew", owner=alice, visibility=Visibility.PUBLIC)

    content = client.get(reverse("recipes:recipe-detail", args=[recipe.pk])).content.decode()

    assert reverse("recipes:recipe-copy", args=[recipe.pk]) in content


def test_copy_via_html_creates_private_owned_copy(logged_in, alice, make_recipe):
    client, me = logged_in
    recipe = make_recipe(name="Alice Public Stew", owner=alice, visibility=Visibility.PUBLIC)

    response = client.post(reverse("recipes:recipe-copy", args=[recipe.pk]))

    assert response.status_code == 302
    from recipes.models import Recipe

    copy = Recipe.objects.get(owner=me, name="Alice Public Stew")
    assert copy.copied_from_id == recipe.pk
    assert copy.visibility == Visibility.PRIVATE


def test_share_modal_renders_for_owner_only(logged_in, alice, make_recipe, user_factory):
    client, me = logged_in
    recipe = make_recipe(name="My Shareable", owner=me, visibility=Visibility.SHARED)

    fragment = client.get(
        reverse("recipes:recipe-share-modal", args=[recipe.pk]), HTTP_HX_REQUEST="true"
    )
    assert fragment.status_code == 200
    assert "Share &ldquo;My Shareable&rdquo;" in fragment.content.decode()

    # A non-owner who can see the recipe (it is PUBLIC) still gets an empty modal body — the
    # sharee list and candidate picker are never built for them.
    others = make_recipe(name="Alice Public", owner=alice, visibility=Visibility.PUBLIC)
    non_owner_fragment = client.get(
        reverse("recipes:recipe-share-modal", args=[others.pk]), HTTP_HX_REQUEST="true"
    )
    assert non_owner_fragment.status_code == 200
    assert non_owner_fragment.content.decode().strip() == ""


def test_share_via_html_grants_and_is_owner_only(logged_in, user_factory, make_recipe):
    client, me = logged_in
    friend = user_factory(username="friend")
    recipe = make_recipe(name="My Recipe", owner=me, visibility=Visibility.SHARED)

    response = client.post(
        reverse("recipes:recipe-share", args=[recipe.pk]),
        {"visibility": "SHARED", "users": [friend.pk]},
    )

    assert response.status_code == 302
    assert Recipe.objects.visible_to(friend).filter(pk=recipe.pk).exists()


def test_update_via_html_denied_for_read_only_holder(logged_in, alice, make_recipe):
    """A recipe shared with (not owned by) the requester is read-only through the HTML form:
    ``OwnedObjectMixin.get_object`` runs ``IsOwnerOrReadOnly`` and a non-owner POST 403s
    before any component parsing, leaving the recipe untouched. Proves ``Recipe`` is wired to
    the mixin's write-side defence (core proves the mixin generically; task 05 review noted the
    Recipe-specific regression test was missing).
    """
    client, me = logged_in
    recipe = make_recipe(name="Alice Stew", owner=alice, visibility=Visibility.SHARED)
    recipe.shared_with.add(me)

    response = client.post(
        reverse("recipes:recipe-update", args=[recipe.pk]),
        {
            "name": "Hijacked",
            "instructions": "x",
            "yield_quantity": "4",
            "yield_unit": recipe.yield_unit_id,
            "role": "OTHER",
        },
    )

    assert response.status_code == 403
    recipe.refresh_from_db()
    assert recipe.name == "Alice Stew"


def test_share_via_html_denied_for_read_only_holder(logged_in, alice, user_factory, make_recipe):
    """Sharing is a right of ownership (``core.services.sharing._require_can_manage_sharing`` →
    ``PermissionDenied``): a read-only holder POSTing to the share view 403s and grants nothing.
    """
    client, me = logged_in
    friend = user_factory(username="friend")
    recipe = make_recipe(name="Alice Roast", owner=alice, visibility=Visibility.SHARED)
    recipe.shared_with.add(me)

    response = client.post(
        reverse("recipes:recipe-share", args=[recipe.pk]),
        {"visibility": "SHARED", "users": [friend.pk]},
    )

    assert response.status_code == 403
    assert not Recipe.objects.visible_to(friend).filter(pk=recipe.pk).exists()


def test_share_via_html_degrades_when_subtree_too_deep(
    logged_in, user_factory, make_recipe, add_sub_recipe, cup
):
    """A sub-recipe chain at the depth cap makes the share cascade's ``walk_dependencies`` raise
    ``DepthExceededError`` (a ``GraphError``). The HTML path must degrade like the REST
    ``share`` action (HTTP 400 there): redirect back with an error message, never a 500.
    """
    client, me = logged_in
    friend = user_factory(username="friend")
    chain = [
        make_recipe(name=f"deep{i}", owner=me, visibility=Visibility.PRIVATE) for i in range(8)
    ]
    for parent, child in zip(chain, chain[1:], strict=False):
        add_sub_recipe(parent, child, 1, cup)

    response = client.post(
        reverse("recipes:recipe-share", args=[chain[0].pk]),
        {"visibility": "SHARED", "users": [friend.pk]},
    )

    assert response.status_code == 302
    assert response.url == reverse("recipes:recipe-detail", args=[chain[0].pk])
    error_messages = [m for m in get_messages(response.wsgi_request) if m.level_tag == "error"]
    assert error_messages, "expected an error message, not a 500"
    assert not Recipe.objects.visible_to(friend).filter(pk=chain[0].pk).exists()


# --- delete ---------------------------------------------------------------------------


def test_delete_via_confirm_removes_recipe(logged_in, make_recipe):
    client, me = logged_in
    recipe = make_recipe(name="Doomed", owner=me, visibility=Visibility.PRIVATE)

    response = client.post(reverse("recipes:recipe-delete", args=[recipe.pk]))

    assert response.status_code == 302
    assert response.url == reverse("recipes:recipe-list")
    assert not Recipe.objects.filter(pk=recipe.pk).exists()


def test_delete_refused_when_recipe_is_used_as_a_subrecipe(
    logged_in, make_recipe, add_sub_recipe, cup
):
    """``RecipeComponent.sub_recipe`` is ``PROTECT``: deleting a recipe another one depends on
    is refused with a message naming the parent, not a 500 (design.md, "Edge cases").
    """
    client, me = logged_in
    marinara = make_recipe(name="Marinara", owner=me, visibility=Visibility.PRIVATE)
    parm = make_recipe(name="Chicken Parm", owner=me, visibility=Visibility.PRIVATE)
    add_sub_recipe(parm, marinara, 1, cup)

    response = client.post(reverse("recipes:recipe-delete", args=[marinara.pk]), follow=True)

    assert Recipe.objects.filter(pk=marinara.pk).exists()
    body = response.content.decode()
    assert "Chicken Parm" in body
    assert "Cannot delete" in body


def test_delete_denied_for_read_only_holder(logged_in, alice, make_recipe):
    client, me = logged_in
    recipe = make_recipe(name="Alice Stew", owner=alice, visibility=Visibility.SHARED)
    recipe.shared_with.add(me)

    response = client.post(reverse("recipes:recipe-delete", args=[recipe.pk]))

    assert response.status_code == 403
    assert Recipe.objects.filter(pk=recipe.pk).exists()


# --- recipe form (05.12) --------------------------------------------------------------


def test_form_creates_recipe_with_components(logged_in, make_recipe, make_ingredient, gram, cup):
    client, me = logged_in
    flour = make_ingredient("Flour", owner=me)
    marinara = make_recipe(name="Marinara", owner=me, visibility=Visibility.PRIVATE)

    response = client.post(
        reverse("recipes:recipe-create"),
        {
            "name": "Pizza",
            "description": "",
            "instructions": "Bake it hot.",
            "yield_quantity": "1",
            "yield_unit": cup.pk,
            "role": "OTHER",
            "source_url": "",
            "component_kind": ["ingredient", "sub_recipe"],
            "component_ref": [str(flour.pk), str(marinara.pk)],
            "component_quantity": ["500", "1"],
            "component_unit": [str(gram.pk), str(cup.pk)],
            "component_note": ["sifted", ""],
        },
    )

    assert response.status_code == 302
    pizza = Recipe.objects.get(owner=me, name="Pizza")
    assert pizza.components.count() == 2
    assert pizza.components.filter(
        ingredient=flour, quantity=Decimal("500"), position=0, note="sifted"
    ).exists()
    assert pizza.components.filter(sub_recipe=marinara, position=1).exists()


def test_form_updates_and_replaces_component_set(
    logged_in, make_recipe, make_ingredient, add_ingredient, gram, cup
):
    client, me = logged_in
    recipe = make_recipe(name="Stew", owner=me, visibility=Visibility.PRIVATE)
    old = make_ingredient("Old Carrot", owner=me)
    add_ingredient(recipe, old, 2, gram)
    new = make_ingredient("New Potato", owner=me)

    response = client.post(
        reverse("recipes:recipe-update", args=[recipe.pk]),
        {
            "name": "Stew",
            "instructions": "Simmer.",
            "yield_quantity": "4",
            "yield_unit": cup.pk,
            "role": "ONE_POT",
            "component_kind": ["ingredient"],
            "component_ref": [str(new.pk)],
            "component_quantity": ["3"],
            "component_unit": [str(gram.pk)],
            "component_note": [""],
        },
    )

    assert response.status_code == 302
    assert list(recipe.components.values_list("ingredient__name", flat=True)) == ["New Potato"]


def test_form_rejects_invisible_ingredient(logged_in, alice, make_ingredient, cup, gram):
    client, me = logged_in
    secret = make_ingredient("Alice Secret", owner=alice, visibility=Visibility.PRIVATE)

    response = client.post(
        reverse("recipes:recipe-create"),
        {
            "name": "Probe",
            "instructions": "x",
            "yield_quantity": "1",
            "yield_unit": cup.pk,
            "role": "OTHER",
            "component_kind": ["ingredient"],
            "component_ref": [str(secret.pk)],
            "component_quantity": ["1"],
            "component_unit": [str(gram.pk)],
            "component_note": [""],
        },
    )

    assert response.status_code == 200
    assert not Recipe.objects.filter(name="Probe").exists()
    assert "not available to you" in response.content.decode()


def test_htmx_add_component_row(logged_in):
    client, _me = logged_in

    response = client.get(
        reverse("recipes:recipe-component-row") + "?kind=sub_recipe",
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "<html" not in content
    assert 'name="component_ref"' in content
    assert 'name="component_quantity"' in content
    assert 'value="sub_recipe"' in content


def test_recipe_form_requires_login(client):
    assert client.get(reverse("recipes:recipe-create")).status_code == 302
