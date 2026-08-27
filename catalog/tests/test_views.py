"""``Plan/04-Units-And-Ingredients/test-plan.md`` — "UI" (04.9-04.12), plus the shared unit
picker partial (04.11).
"""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from catalog.models import Ingredient
from core.models import Visibility

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(user_factory):
    return user_factory(username="alice")


@pytest.fixture
def logged_in(client, user_factory):
    user = user_factory(username="me")
    client.force_login(user)
    return client, user


# --- list ------------------------------------------------------------------------------


def test_ingredient_list_requires_login(client):
    response = client.get(reverse("catalog:ingredient-list"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_list_shows_only_visible(logged_in, alice, make_ingredient):
    client, me = logged_in
    make_ingredient(name="My Oregano", owner=me, visibility=Visibility.PRIVATE)
    make_ingredient(name="Alice Secret Spice", owner=alice, visibility=Visibility.PRIVATE)

    response = client.get(reverse("catalog:ingredient-list"))

    content = response.content.decode()
    assert "My Oregano" in content
    assert "Alice Secret Spice" not in content


def test_htmx_search_returns_fragment(logged_in, make_ingredient):
    client, me = logged_in
    make_ingredient(name="Cumin", owner=me, visibility=Visibility.PRIVATE)

    response = client.get(
        reverse("catalog:ingredient-list") + "?search=cum", HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "<html" not in content
    assert '<nav class="nav-top"' not in content
    assert "Cumin" in content


def test_search_filters_the_list(logged_in, make_ingredient):
    client, me = logged_in
    make_ingredient(name="Cinnamon", owner=me, visibility=Visibility.PRIVATE)
    make_ingredient(name="Paprika", owner=me, visibility=Visibility.PRIVATE)

    response = client.get(reverse("catalog:ingredient-list") + "?search=cinn")

    content = response.content.decode()
    assert "Cinnamon" in content
    assert "Paprika" not in content


def test_tag_filter_narrows_the_list(logged_in, make_ingredient, make_tag):
    client, me = logged_in
    veg = make_tag("vegetarian", kind="DIET")
    tagged = make_ingredient(name="Lentils", owner=me, visibility=Visibility.PRIVATE)
    tagged.tags.add(veg)
    make_ingredient(name="Bacon", owner=me, visibility=Visibility.PRIVATE)

    response = client.get(reverse("catalog:ingredient-list") + f"?tags={veg.slug}")

    content = response.content.decode()
    assert "Lentils" in content
    assert "Bacon" not in content


def test_empty_state_when_nothing_matches(logged_in):
    client, _ = logged_in

    response = client.get(reverse("catalog:ingredient-list") + "?search=nothingmatchesthis")

    assert "No ingredients found" in response.content.decode()


# --- detail / form -------------------------------------------------------------------


def test_create_via_form(logged_in, make_unit):
    client, me = logged_in
    gram = make_unit("gram")

    response = client.post(
        reverse("catalog:ingredient-create"),
        {"name": "  Smoked Paprika  ", "default_unit": gram.pk, "tags": []},
    )

    assert response.status_code == 302
    created = Ingredient.objects.get(name="Smoked Paprika")
    assert created.owner == me
    assert created.is_system is False
    assert created.visibility == Visibility.PRIVATE


def test_edit_via_form(logged_in, make_ingredient, make_unit):
    client, me = logged_in
    make_unit("gram")
    ingredient = make_ingredient(name="Thyme", owner=me, visibility=Visibility.PRIVATE)

    response = client.post(
        reverse("catalog:ingredient-update", args=[ingredient.pk]),
        {
            "name": "Fresh Thyme",
            "default_unit": ingredient.default_unit_id,
            "is_staple": "on",
            "tags": [],
        },
    )

    assert response.status_code == 302
    ingredient.refresh_from_db()
    assert ingredient.name == "Fresh Thyme"
    assert ingredient.is_staple is True


def test_cannot_edit_others_ingredient_via_html(logged_in, alice, make_ingredient):
    client, _ = logged_in
    obj = make_ingredient(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)

    assert client.get(reverse("catalog:ingredient-update", args=[obj.pk])).status_code == 404
    assert client.get(reverse("catalog:ingredient-detail", args=[obj.pk])).status_code == 404


def test_detail_page_renders_for_owner(logged_in, make_ingredient):
    client, me = logged_in
    ingredient = make_ingredient(name="Bay Leaf", owner=me, visibility=Visibility.PRIVATE)

    response = client.get(reverse("catalog:ingredient-detail", args=[ingredient.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Bay Leaf" in content
    assert reverse("catalog:ingredient-update", args=[ingredient.pk]) in content


def test_delete_via_confirm(logged_in, make_ingredient):
    client, me = logged_in
    ingredient = make_ingredient(name="Old Spice", owner=me, visibility=Visibility.PRIVATE)

    response = client.post(reverse("catalog:ingredient-delete", args=[ingredient.pk]))

    assert response.status_code == 302
    assert not Ingredient.objects.filter(pk=ingredient.pk).exists()


# --- copy / share via the HTML intermediary views -----------------------------------


def test_copy_system_ingredient_via_html(logged_in, make_ingredient):
    client, me = logged_in
    system = make_ingredient(name="Sea Salt")

    response = client.post(reverse("catalog:ingredient-copy", args=[system.pk]))

    assert response.status_code == 302
    copy = Ingredient.objects.get(owner=me, name="Sea Salt")
    assert copy.copied_from_id == system.pk
    assert copy.visibility == Visibility.PRIVATE
    assert response.url == reverse("catalog:ingredient-detail", args=[copy.pk])


def test_share_via_html_grants_and_is_owner_only(logged_in, user_factory, make_ingredient):
    client, me = logged_in
    friend = user_factory(username="friend")
    ingredient = make_ingredient(name="My Harissa", owner=me, visibility=Visibility.SHARED)

    response = client.post(
        reverse("catalog:ingredient-share", args=[ingredient.pk]),
        {"visibility": "SHARED", "users": [friend.pk]},
    )

    assert response.status_code == 302
    assert Ingredient.objects.visible_to(friend).filter(pk=ingredient.pk).exists()


def test_share_modal_renders_for_owner(logged_in, make_ingredient):
    client, me = logged_in
    ingredient = make_ingredient(name="My Zaatar", owner=me, visibility=Visibility.SHARED)

    full = client.get(reverse("catalog:ingredient-share-modal", args=[ingredient.pk]))
    fragment = client.get(
        reverse("catalog:ingredient-share-modal", args=[ingredient.pk]), HTTP_HX_REQUEST="true"
    )

    assert full.status_code == 200
    assert 'class="nav-top"' in full.content.decode()
    frag = fragment.content.decode()
    assert "<html" not in frag
    assert "Share &ldquo;My Zaatar&rdquo;" in frag
    assert reverse("catalog:ingredient-share", args=[ingredient.pk]) in frag


def test_share_modal_body_hidden_from_non_owner(client, user_factory, make_ingredient):
    owner = user_factory(username="owner")
    other = user_factory(username="other")
    ingredient = make_ingredient(name="Owner Zaatar", owner=owner, visibility=Visibility.SHARED)
    ingredient.shared_with.add(other)
    client.force_login(other)

    response = client.get(
        reverse("catalog:ingredient-share-modal", args=[ingredient.pk]), HTTP_HX_REQUEST="true"
    )

    # Visible object, so 200 (not 404), but the modal self-gates its body on ownership.
    assert response.status_code == 200
    assert "Currently shared with" not in response.content.decode()


def test_detail_shows_copy_button_for_non_owner(client, user_factory, make_ingredient):
    other = user_factory(username="other")
    system = make_ingredient(name="Built-in Basil")
    client.force_login(other)

    response = client.get(reverse("catalog:ingredient-detail", args=[system.pk]))

    assert response.status_code == 200
    assert reverse("catalog:ingredient-copy", args=[system.pk]) in response.content.decode()


def test_share_via_html_rejected_for_non_owner(client, user_factory, make_ingredient):
    owner = user_factory(username="owner")
    other = user_factory(username="other")
    ingredient = make_ingredient(name="Owner Harissa", owner=owner, visibility=Visibility.SHARED)
    ingredient.shared_with.add(other)
    client.force_login(other)

    response = client.post(
        reverse("catalog:ingredient-share", args=[ingredient.pk]),
        {"visibility": "PUBLIC"},
    )

    assert response.status_code == 403
    ingredient.refresh_from_db()
    assert ingredient.visibility == Visibility.SHARED


# --- quick-add (task 05 contract) --------------------------------------------------


def test_quick_add_returns_row_fragment(logged_in, make_unit):
    client, me = logged_in
    gram = make_unit("gram")

    response = client.post(
        reverse("catalog:ingredient-quick-add"),
        {"name": "Sumac", "default_unit": gram.pk},
    )

    assert response.status_code == 201
    content = response.content.decode()
    assert "<html" not in content
    assert "Sumac" in content
    ingredient = Ingredient.objects.get(owner=me, name="Sumac")
    assert f'data-ingredient-id="{ingredient.pk}"' in content
    assert f'data-default-unit-id="{gram.pk}"' in content


def test_quick_add_is_idempotent_on_name(logged_in, make_unit, make_ingredient):
    client, me = logged_in
    gram = make_unit("gram")
    existing = make_ingredient(name="Sumac", owner=me, visibility=Visibility.PRIVATE)

    response = client.post(
        reverse("catalog:ingredient-quick-add"),
        {"name": "sumac", "default_unit": gram.pk},
    )

    assert response.status_code == 200
    assert Ingredient.objects.filter(owner=me, name__iexact="Sumac").count() == 1
    assert f'data-ingredient-id="{existing.pk}"' in response.content.decode()


def test_quick_add_requires_a_name(logged_in):
    client, _ = logged_in

    response = client.post(reverse("catalog:ingredient-quick-add"), {"name": "  "})

    assert response.status_code == 400
    assert "required" in response.content.decode().lower()


def test_quick_add_requires_login(client):
    response = client.post(reverse("catalog:ingredient-quick-add"), {"name": "Sumac"})

    assert response.status_code == 302


# --- shared unit picker partial (04.11) -------------------------------------------


def test_unit_select_partial_groups_by_dimension(make_unit):
    gram = make_unit("gram")
    cup = make_unit("cup")
    each = make_unit("each")
    from catalog.models import Unit

    html = render_to_string(
        "_partials/_unit_select.html",
        {"units": Unit.objects.all(), "name": "unit", "selected": cup.pk},
    )

    assert '<optgroup label="Mass">' in html
    assert '<optgroup label="Volume">' in html
    assert '<optgroup label="Count">' in html
    assert f'<option value="{cup.pk}" selected>' in html
    assert f'<option value="{gram.pk}">' in html
    assert str(each.pk) in html


def test_unit_select_partial_blank_option_only_when_optional(make_unit):
    make_unit("gram")
    from catalog.models import Unit

    optional = render_to_string(
        "_partials/_unit_select.html", {"units": Unit.objects.all(), "name": "unit"}
    )
    required = render_to_string(
        "_partials/_unit_select.html",
        {"units": Unit.objects.all(), "name": "unit", "required": 1},
    )

    assert '<option value="">' in optional
    assert '<option value="">' not in required
    assert "required" in required
