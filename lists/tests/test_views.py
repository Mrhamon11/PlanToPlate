"""HTMX UI for lists and shopping lists (``Plan/07-Lists-And-Shopping/test-plan.md``, "UI").

The load-bearing behaviours: a shopping list follows a supermarket's aisle shape (alphabetical
when untagged), one-tap check is an HTMX fragment that refreshes the progress counter
out-of-band, generated lines are styled apart from manual ones (no "from …" caption — 07.21),
a tombstoned reference renders rather than 500ing, and a shared list is read-only for the
recipient.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from catalog.models import Tag
from lists.models import ItemSource, ListItem, ListKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def shopping(make_list, alice):
    return make_list("Groceries", owner=alice, kind=ListKind.SHOPPING)


def _login(client, user):
    client.force_login(user)
    return client


# --- aisle grouping -----------------------------------------------------------------------


def test_shopping_list_groups_by_aisle(client, shopping, make_ingredient, gram, alice):
    produce = Tag.objects.create(name="Produce")
    dairy = Tag.objects.create(name="Dairy")
    onion = make_ingredient("Onion", owner=alice)
    onion.tags.add(produce)
    milk = make_ingredient("Milk", owner=alice)
    milk.tags.add(dairy)
    ListItem.objects.create(list=shopping, ingredient=onion, quantity=Decimal("2"), unit=gram)
    ListItem.objects.create(list=shopping, ingredient=milk, quantity=Decimal("1"), unit=gram)

    body = _login(client, alice).get(shopping.get_absolute_url()).content.decode()

    assert "<h2>Produce</h2>" in body
    assert "<h2>Dairy</h2>" in body
    # named aisles are alphabetical: Dairy before Produce
    assert body.index("<h2>Dairy</h2>") < body.index("<h2>Produce</h2>")


def test_ungrouped_items_fall_back_to_alphabetical(client, shopping, alice):
    for text in ("Zucchini", "Apple", "Mango"):
        ListItem.objects.create(list=shopping, text=text)

    body = _login(client, alice).get(shopping.get_absolute_url()).content.decode()

    assert "<h2>Other</h2>" in body
    assert body.index("Apple") < body.index("Mango") < body.index("Zucchini")


# --- one-tap check ----------------------------------------------------------------------


def test_htmx_check_returns_fragment(client, shopping, alice):
    item = ListItem.objects.create(list=shopping, text="Bread")
    url = reverse("lists:item-check", args=[shopping.pk, item.pk])

    response = _login(client, alice).post(url, HTTP_HX_REQUEST="true")
    body = response.content.decode()

    assert response.status_code == 200
    item.refresh_from_db()
    assert item.is_checked is True
    # the row fragment, and the progress counter refreshed out-of-band
    assert f"shopping-item-{item.pk}" in body
    assert 'id="shopping-progress"' in body
    assert 'hx-swap-oob="true"' in body
    assert "1 of 1 item" in body


def test_no_js_check_preserves_the_page_param(client, shopping, alice):
    """A no-JS check on page 2 of a long list redirects back to page 2, not page 1."""
    item = ListItem.objects.create(list=shopping, text="Bread")

    response = _login(client, alice).post(
        reverse("lists:item-check", args=[shopping.pk, item.pk]), {"page": "2"}
    )

    assert response.status_code == 302
    assert response.url == f"{shopping.get_absolute_url()}?page=2"


def test_tap_targets_on_shopping_items(client, shopping, alice):
    ListItem.objects.create(list=shopping, text="Bread")

    body = _login(client, alice).get(shopping.get_absolute_url()).content.decode()
    assert 'class="shopping-check"' in body

    css = (Path(settings.BASE_DIR) / "static/css/components.css").read_text()
    check_rule = css.split(".shopping-check {", 1)[1].split("}", 1)[0]
    assert "min-height: var(--tap-target)" in check_rule


# --- generated vs manual --------------------------------------------------------------


def test_generated_items_visually_distinguished(client, shopping, make_ingredient, gram, alice):
    ListItem.objects.create(
        list=shopping,
        ingredient=make_ingredient("Flour", owner=alice),
        quantity=Decimal("500"),
        unit=gram,
        source=ItemSource.GENERATED,
    )

    body = _login(client, alice).get(shopping.get_absolute_url()).content.decode()

    assert "shopping-item--generated" in body


def test_generated_item_records_dish_but_shows_no_label(
    client, shopping, make_ingredient, make_dish, gram, alice
):
    """A single-contributor generated line still records its dish as data (task 08 uses it),
    but the list UI renders no "from …" caption (2026-09-05 dev-test decision, 07.21).
    """
    dish = make_dish("Chicken Parm", owner=alice)
    item = ListItem.objects.create(
        list=shopping,
        ingredient=make_ingredient("Parmesan", owner=alice),
        quantity=Decimal("100"),
        unit=gram,
        dish=dish,
        source=ItemSource.GENERATED,
    )

    body = _login(client, alice).get(shopping.get_absolute_url()).content.decode()

    item.refresh_from_db()
    assert item.dish_id == dish.pk
    assert "from Chicken Parm" not in body
    assert "shopping-item-meta" not in body


def test_tombstoned_item_renders(client, shopping, make_recipe, alice):
    recipe = make_recipe("Old Recipe", owner=alice)
    item = ListItem.objects.create(list=shopping, recipe=recipe)  # content-only line
    recipe.delete()
    item.refresh_from_db()
    assert item.recipe_id is None and item.text == "(deleted recipe)"

    response = _login(client, alice).get(shopping.get_absolute_url())

    assert response.status_code == 200
    assert "(deleted recipe)" in response.content.decode()


# --- regeneration warning -----------------------------------------------------------------


def test_regenerate_warns_when_items_checked(client, shopping, make_ingredient, gram, alice):
    make = lambda name, checked: ListItem.objects.create(  # noqa: E731
        list=shopping,
        ingredient=make_ingredient(name, owner=alice),
        quantity=Decimal("1"),
        unit=gram,
        source=ItemSource.GENERATED,
        is_checked=checked,
    )
    make("Rice", True)
    make("Beans", False)
    url = reverse("lists:regenerate-confirm", args=[shopping.pk])

    body = _login(client, alice).get(url, HTTP_HX_REQUEST="true").content.decode()

    assert "checked off" in body
    assert "loses that shopping progress" in body


def test_regenerate_confirm_has_no_warning_without_checked(
    client, shopping, make_ingredient, gram, alice
):
    ListItem.objects.create(
        list=shopping,
        ingredient=make_ingredient("Rice", owner=alice),
        quantity=Decimal("1"),
        unit=gram,
        source=ItemSource.GENERATED,
    )
    url = reverse("lists:regenerate-confirm", args=[shopping.pk])

    body = _login(client, alice).get(url, HTTP_HX_REQUEST="true").content.decode()

    assert "loses that shopping progress" not in body


def test_regenerate_clears_generated_keeps_manual(client, shopping, make_ingredient, gram, alice):
    ListItem.objects.create(
        list=shopping,
        ingredient=make_ingredient("Rice", owner=alice),
        quantity=Decimal("1"),
        unit=gram,
        source=ItemSource.GENERATED,
    )
    ListItem.objects.create(list=shopping, text="Batteries", source=ItemSource.MANUAL)

    _login(client, alice).post(reverse("lists:regenerate", args=[shopping.pk]))

    assert [i.text for i in shopping.items.all()] == ["Batteries"]


# --- read-only when shared ------------------------------------------------------------


def test_shared_list_is_read_only(client, make_list, alice, bob):
    lst = make_list("Alice Shopping", owner=alice, kind=ListKind.SHOPPING, visibility="SHARED")
    lst.shared_with.add(bob)
    item = ListItem.objects.create(list=lst, text="milk")

    bob_client = _login(client, bob)

    # can open it
    assert bob_client.get(lst.get_absolute_url()).status_code == 200
    # cannot check an item off
    check = reverse("lists:item-check", args=[lst.pk, item.pk])
    assert bob_client.post(check, HTTP_HX_REQUEST="true").status_code == 403
    item.refresh_from_db()
    assert item.is_checked is False
    # cannot add or clear
    assert (
        bob_client.post(reverse("lists:item-add", args=[lst.pk]), {"text": "eggs"}).status_code
        == 403
    )
    assert bob_client.post(reverse("lists:clear-checked", args=[lst.pk])).status_code == 403
    # the read-only view offers no check form
    body = bob_client.get(lst.get_absolute_url()).content.decode()
    assert f"lists/{lst.pk}/items/{item.pk}/check/" not in body


# --- index -----------------------------------------------------------------------------


def test_list_index_groups_by_kind_and_pins_default(client, make_list, alice):
    make_list("Ideas", owner=alice, kind=ListKind.GENERIC)
    make_list(
        "Shopping List",
        owner=alice,
        kind=ListKind.SHOPPING,
        is_default_shopping_list=True,
    )
    make_list("Aardvark shopping", owner=alice, kind=ListKind.SHOPPING)

    body = _login(client, alice).get(reverse("lists:index")).content.decode()

    # SHOPPING group heading before the GENERIC ("List") group heading
    assert body.index("<h2>Shopping list</h2>") < body.index("<h2>List</h2>")
    # default list pinned above the alphabetically-earlier non-default one
    assert body.index("Shopping List") < body.index("Aardvark shopping")


def test_index_counts_do_not_leak_invisible_content(client, make_list, make_recipe, alice, bob):
    """A shared list's index card shows a line count, never the name of a reference the
    recipient cannot see (design.md, "Security notes").
    """
    secret = make_recipe("Secret Sauce", owner=alice, visibility="PRIVATE")
    lst = make_list("Alice Shared", owner=alice, kind=ListKind.GENERIC, visibility="SHARED")
    lst.shared_with.add(bob)
    ListItem.objects.create(list=lst, recipe=secret)

    body = _login(client, bob).get(reverse("lists:index")).content.decode()

    assert "1 item" in body
    assert "Secret Sauce" not in body


# --- generic list reordering --------------------------------------------------------------


def test_move_item_view_reorders_generic_list(client, make_list, add_item, alice):
    lst = make_list("Ideas", owner=alice, kind=ListKind.GENERIC)
    add_item(lst, text="a", position=0)
    b = add_item(lst, text="b", position=1)
    add_item(lst, text="c", position=2)

    response = _login(client, alice).post(
        reverse("lists:item-move", args=[lst.pk, b.pk]), {"direction": "down"}
    )

    assert response.status_code == 302
    assert [i.text for i in lst.items.all()] == ["a", "c", "b"]


def test_move_item_view_noop_moving_first_item_up(client, make_list, add_item, alice):
    lst = make_list("Ideas", owner=alice, kind=ListKind.GENERIC)
    a = add_item(lst, text="a", position=0)
    add_item(lst, text="b", position=1)

    _login(client, alice).post(reverse("lists:item-move", args=[lst.pk, a.pk]), {"direction": "up"})

    assert [i.text for i in lst.items.all()] == ["a", "b"]


# --- "Add to list" from a recipe / dish page ---------------------------------------------


def test_add_to_list_rejects_non_numeric_list_id(client, make_recipe, alice):
    """A crafted ``list=abc`` POST is a 302 back to the object page with an error message,
    never a 500 (``int("abc")`` used to blow up the queryset).
    """
    recipe = make_recipe("Pancakes", owner=alice)

    response = _login(client, alice).post(
        reverse("lists:add-object", args=["recipe", recipe.pk]), {"list": "abc"}
    )

    assert response.status_code == 302
    assert response.url == recipe.get_absolute_url()
    assert not ListItem.objects.exists()


# --- 07.15: the native remove form must render a CSRF token -------------------------------


def test_shopping_remove_form_deletes_with_csrf_enforced(shopping, alice):
    """The row's native remove ``<form>`` must render a ``csrfmiddlewaretoken`` field even
    though it is reached through ``{% include ... only %}`` — the missing token is what made
    the ``×`` button 403 in a real browser (07.15).
    """
    item = ListItem.objects.create(list=shopping, text="Bread")
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(alice)

    body = csrf_client.get(shopping.get_absolute_url()).content.decode()

    remove_action = reverse("lists:item-delete", args=[shopping.pk, item.pk])
    form_html = body.split(remove_action, 1)[1].split("</form>", 1)[0]
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', form_html)
    assert match, "remove form rendered without a CSRF field"

    response = csrf_client.post(remove_action, {"csrfmiddlewaretoken": match.group(1)})

    assert response.status_code == 302
    assert not shopping.items.filter(pk=item.pk).exists()


# --- 07.16: an explicit recipe/dish kind must not fall through to free text --------------


def test_generic_add_recipe_kind_without_ref_errors(client, make_list, alice):
    lst = make_list("Ideas", owner=alice, kind=ListKind.GENERIC)

    response = _login(client, alice).post(
        reverse("lists:item-add", args=[lst.pk]),
        {"kind": "recipe", "recipe_ref": "", "text": "free text sneaking in"},
        follow=True,
    )

    assert lst.items.count() == 0
    assert "Pick a recipe" in response.content.decode()


def test_generic_add_dish_kind_without_ref_errors(client, make_list, alice):
    lst = make_list("Ideas", owner=alice, kind=ListKind.GENERIC)

    response = _login(client, alice).post(
        reverse("lists:item-add", args=[lst.pk]),
        {"kind": "dish", "dish_ref": "", "text": "free text sneaking in"},
        follow=True,
    )

    assert lst.items.count() == 0
    assert "Pick a dish" in response.content.decode()


# --- 07.21: the list UI renders no "from …" caption at all ----------------------------


def test_merged_and_deleted_dish_generated_lines_render_without_caption(
    client, shopping, make_ingredient, make_dish, gram, alice
):
    """A merged generated line (no single contributing dish) and a generated line whose dish
    was since deleted both still render fine — no 500, and no "from …" caption of any kind
    (07.21). The generated-vs-manual styling is the only marker left.
    """
    ListItem.objects.create(
        list=shopping,
        ingredient=make_ingredient("Onion", owner=alice),
        quantity=Decimal("3"),
        unit=gram,
        source=ItemSource.GENERATED,
    )
    dish = make_dish("Gone Dish", owner=alice)
    ListItem.objects.create(
        list=shopping,
        ingredient=make_ingredient("Garlic", owner=alice),
        quantity=Decimal("2"),
        unit=gram,
        dish=dish,
        source=ItemSource.GENERATED,
    )
    dish.delete()  # SET_NULL — the ingredient line survives, dish_id now None

    response = _login(client, alice).get(shopping.get_absolute_url())

    assert response.status_code == 200
    body = response.content.decode()
    assert "shopping-item--generated" in body
    assert "shopping-item-meta" not in body
    assert "from the meal plan" not in body
    assert "from Gone Dish" not in body


# --- 07.18: dismissable menus / typeahead --------------------------------------------------


def test_menus_script_loaded_without_breaking_native_details(client, alice):
    body = _login(client, alice).get(reverse("lists:index")).content.decode()

    assert "js/menus.js" in body
    # the nav menu stays a native <details> — outside-click dismissal is enhancement only
    assert '<details class="nav-menu">' in body


# --- 07.19: Check all / Clear all -----------------------------------------------------


def test_shopping_detail_offers_check_all_and_clear_all(client, shopping, alice):
    ListItem.objects.create(list=shopping, text="Bread")

    body = _login(client, alice).get(shopping.get_absolute_url()).content.decode()

    assert reverse("lists:check-all", args=[shopping.pk]) in body
    assert reverse("lists:clear-all-confirm", args=[shopping.pk]) in body


def test_check_all_view_checks_every_item(client, shopping, alice):
    ListItem.objects.create(list=shopping, text="a")
    ListItem.objects.create(list=shopping, text="b", is_checked=True)

    response = _login(client, alice).post(reverse("lists:check-all", args=[shopping.pk]))

    assert response.status_code == 302
    assert all(i.is_checked for i in shopping.items.all())


def test_clear_all_needs_the_confirm_step_then_empties(client, shopping, alice):
    ListItem.objects.create(list=shopping, text="a")
    ListItem.objects.create(list=shopping, text="b")
    session = _login(client, alice)

    confirm = session.get(reverse("lists:clear-all-confirm", args=[shopping.pk]))
    assert confirm.status_code == 200
    assert reverse("lists:clear-all", args=[shopping.pk]) in confirm.content.decode()
    assert shopping.items.count() == 2  # GETting the confirm changes nothing

    done = session.post(reverse("lists:clear-all", args=[shopping.pk]))
    assert done.status_code == 302
    assert shopping.items.count() == 0


def test_check_all_and_clear_all_are_owner_only(client, make_list, alice, bob):
    lst = make_list("Alice Shopping", owner=alice, kind=ListKind.SHOPPING, visibility="SHARED")
    lst.shared_with.add(bob)
    item = ListItem.objects.create(list=lst, text="milk")

    bob_client = _login(client, bob)

    assert bob_client.post(reverse("lists:check-all", args=[lst.pk])).status_code == 403
    assert bob_client.get(reverse("lists:clear-all-confirm", args=[lst.pk])).status_code == 403
    assert bob_client.post(reverse("lists:clear-all", args=[lst.pk])).status_code == 403
    item.refresh_from_db()
    assert item.is_checked is False
    assert lst.items.count() == 1


# --- 07.20: "Check all" toggles to "Uncheck all" -------------------------------------


def test_check_all_button_when_not_all_checked_checks_every_item(client, shopping, alice):
    ListItem.objects.create(list=shopping, text="a")
    ListItem.objects.create(list=shopping, text="b", is_checked=True)
    session = _login(client, alice)

    body = session.get(shopping.get_absolute_url()).content.decode()
    assert ">Check all</button>" in body
    assert ">Uncheck all</button>" not in body

    response = session.post(reverse("lists:check-all", args=[shopping.pk]), {"is_checked": "true"})

    assert response.status_code == 302
    assert all(i.is_checked for i in shopping.items.all())


def test_uncheck_all_button_when_all_checked_unchecks_every_item(client, shopping, alice):
    ListItem.objects.create(list=shopping, text="a", is_checked=True)
    ListItem.objects.create(list=shopping, text="b", is_checked=True)
    session = _login(client, alice)

    body = session.get(shopping.get_absolute_url()).content.decode()
    assert ">Uncheck all</button>" in body
    assert ">Check all</button>" not in body

    response = session.post(reverse("lists:check-all", args=[shopping.pk]), {"is_checked": "false"})

    assert response.status_code == 302
    assert not any(i.is_checked for i in shopping.items.all())


def test_check_all_toggle_is_owner_only(client, make_list, alice, bob):
    lst = make_list("Alice Shopping", owner=alice, kind=ListKind.SHOPPING, visibility="SHARED")
    lst.shared_with.add(bob)
    item = ListItem.objects.create(list=lst, text="milk", is_checked=True)

    bob_client = _login(client, bob)
    response = bob_client.post(reverse("lists:check-all", args=[lst.pk]), {"is_checked": "false"})

    assert response.status_code == 403
    item.refresh_from_db()
    assert item.is_checked is True


# --- 07.22: "Clear all" on the generic list detail ---------------------------------


def test_generic_list_detail_offers_clear_all(client, make_list, alice):
    lst = make_list("Ideas", owner=alice, kind=ListKind.GENERIC)
    ListItem.objects.create(list=lst, text="something")

    body = _login(client, alice).get(lst.get_absolute_url()).content.decode()

    assert reverse("lists:clear-all-confirm", args=[lst.pk]) in body
    assert reverse("lists:delete", args=[lst.pk]) in body


def test_generic_list_clear_all_empties_after_confirm(client, make_list, alice):
    lst = make_list("Ideas", owner=alice, kind=ListKind.GENERIC)
    ListItem.objects.create(list=lst, text="a")
    ListItem.objects.create(list=lst, text="b")
    session = _login(client, alice)

    confirm = session.get(reverse("lists:clear-all-confirm", args=[lst.pk]))
    assert confirm.status_code == 200
    assert lst.items.count() == 2

    done = session.post(reverse("lists:clear-all", args=[lst.pk]))
    assert done.status_code == 302
    assert lst.items.count() == 0


def test_generic_list_clear_all_is_owner_only(client, make_list, alice, bob):
    lst = make_list("Ideas", owner=alice, kind=ListKind.GENERIC, visibility="SHARED")
    lst.shared_with.add(bob)
    ListItem.objects.create(list=lst, text="a")

    bob_client = _login(client, bob)

    assert bob_client.get(reverse("lists:clear-all-confirm", args=[lst.pk])).status_code == 403
    assert bob_client.post(reverse("lists:clear-all", args=[lst.pk])).status_code == 403
    assert lst.items.count() == 1


# --- 07.23: inline edit of an item's quantity and unit --------------------------------


@pytest.fixture
def qty_item(shopping, make_ingredient, gram, alice):
    return ListItem.objects.create(
        list=shopping,
        ingredient=make_ingredient("Flour", owner=alice),
        quantity=Decimal("2"),
        unit=gram,
    )


def test_owner_edits_quantity_and_unit_htmx_returns_row(
    client, shopping, qty_item, kilogram, alice
):
    url = reverse("lists:item-edit", args=[shopping.pk, qty_item.pk])

    response = _login(client, alice).post(
        url, {"quantity": "1.5", "unit": kilogram.pk}, HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert f'id="shopping-item-{qty_item.pk}"' in body
    assert "1.5" in body and "kg" in body
    qty_item.refresh_from_db()
    assert qty_item.quantity == Decimal("1.500")
    assert qty_item.unit == kilogram


def test_edit_quantity_no_js_redirects_and_keeps_page(client, shopping, qty_item, kilogram, alice):
    response = _login(client, alice).post(
        reverse("lists:item-edit", args=[shopping.pk, qty_item.pk]),
        {"quantity": "3", "unit": kilogram.pk, "page": "2"},
    )

    assert response.status_code == 302
    assert response.url == f"{shopping.get_absolute_url()}?page=2"
    qty_item.refresh_from_db()
    assert qty_item.quantity == Decimal("3.000")


def test_edit_item_is_owner_only(client, make_list, make_ingredient, gram, alice, bob):
    lst = make_list("Shared", owner=alice, kind=ListKind.SHOPPING, visibility="SHARED")
    lst.shared_with.add(bob)
    item = ListItem.objects.create(
        list=lst, ingredient=make_ingredient("Flour", owner=alice), quantity=Decimal("2"), unit=gram
    )

    response = _login(client, bob).post(
        reverse("lists:item-edit", args=[lst.pk, item.pk]), {"quantity": "9", "unit": gram.pk}
    )

    assert response.status_code == 403
    item.refresh_from_db()
    assert item.quantity == Decimal("2.000")


def test_edit_unit_without_quantity_is_rejected(client, shopping, qty_item, gram, alice):
    response = _login(client, alice).post(
        reverse("lists:item-edit", args=[shopping.pk, qty_item.pk]),
        {"quantity": "", "unit": gram.pk},
    )

    assert response.status_code == 302
    qty_item.refresh_from_db()
    assert qty_item.quantity == Decimal("2.000")


def test_edit_can_clear_quantity_to_none(client, shopping, qty_item, alice):
    response = _login(client, alice).post(
        reverse("lists:item-edit", args=[shopping.pk, qty_item.pk]),
        {"quantity": "", "unit": ""},
    )

    assert response.status_code == 302
    qty_item.refresh_from_db()
    assert qty_item.quantity is None
    assert qty_item.unit is None


def test_edit_generated_line_stays_generated(
    client, shopping, make_ingredient, gram, kilogram, alice
):
    item = ListItem.objects.create(
        list=shopping,
        ingredient=make_ingredient("Flour", owner=alice),
        quantity=Decimal("500"),
        unit=gram,
        source=ItemSource.GENERATED,
    )

    _login(client, alice).post(
        reverse("lists:item-edit", args=[shopping.pk, item.pk]),
        {"quantity": "1", "unit": kilogram.pk},
    )

    item.refresh_from_db()
    assert item.source == ItemSource.GENERATED
    assert item.quantity == Decimal("1.000")


@pytest.mark.parametrize("bad_quantity", ["nan", "Infinity", "-Infinity", "-3", "123456789"])
def test_edit_rejects_non_finite_or_oversized_quantity_without_500(
    client, shopping, qty_item, gram, alice, bad_quantity
):
    response = _login(client, alice).post(
        reverse("lists:item-edit", args=[shopping.pk, qty_item.pk]),
        {"quantity": bad_quantity, "unit": gram.pk},
    )

    assert response.status_code == 302
    qty_item.refresh_from_db()
    assert qty_item.quantity == Decimal("2.000")
    assert qty_item.unit == gram


def test_edit_rejects_unknown_unit(client, shopping, qty_item, gram, alice):
    response = _login(client, alice).post(
        reverse("lists:item-edit", args=[shopping.pk, qty_item.pk]),
        {"quantity": "2", "unit": "999999"},
    )

    assert response.status_code == 302
    qty_item.refresh_from_db()
    assert qty_item.unit == gram


def test_shopping_row_shows_qty_edit_for_owner_not_for_shared_viewer(
    shopping, qty_item, alice, bob
):
    owner_body = _login(Client(), alice).get(shopping.get_absolute_url()).content.decode()
    assert "item-qty-edit" in owner_body
    assert reverse("lists:item-edit", args=[shopping.pk, qty_item.pk]) in owner_body
    # the inline-edit form carries a CSRF token even under {% include ... only %} (cf. 07.15)
    edit_fragment = owner_body.split("item-qty-edit-form", 1)[1][:400]
    assert "csrfmiddlewaretoken" in edit_fragment

    shopping.visibility = "SHARED"
    shopping.save()
    shopping.shared_with.add(bob)

    shared_body = _login(Client(), bob).get(shopping.get_absolute_url()).content.decode()
    assert "item-qty-edit" not in shared_body


def test_generic_list_row_with_quantity_can_be_edited(
    client, make_list, make_ingredient, gram, kilogram, alice
):
    lst = make_list("Ideas", owner=alice, kind=ListKind.GENERIC)
    item = ListItem.objects.create(
        list=lst,
        ingredient=make_ingredient("Flour", owner=alice),
        quantity=Decimal("2"),
        unit=gram,
    )

    session = _login(client, alice)
    body = session.get(lst.get_absolute_url()).content.decode()
    assert "item-qty-edit" in body

    response = session.post(
        reverse("lists:item-edit", args=[lst.pk, item.pk]),
        {"quantity": "1", "unit": kilogram.pk},
    )

    assert response.status_code == 302
    assert response.url == lst.get_absolute_url()
    item.refresh_from_db()
    assert item.quantity == Decimal("1.000")
    assert item.unit == kilogram


def test_generic_list_text_row_has_no_qty_edit(client, make_list, alice):
    lst = make_list("Ideas", owner=alice, kind=ListKind.GENERIC)
    ListItem.objects.create(list=lst, text="batteries")

    body = _login(client, alice).get(lst.get_absolute_url()).content.decode()

    assert "item-qty-edit" not in body


# --- 07.24: the action bar refreshes out-of-band after a one-tap check --------------


def _actions_fragment(body: str) -> str:
    """The OOB #shopping-actions div returned in a check-toggle fragment."""
    return body.split('id="shopping-actions"', 1)[1].split("</div>", 1)[0]


def test_one_tap_check_reveals_clear_checked_button_oob(client, shopping, alice):
    item = ListItem.objects.create(list=shopping, text="Bread")
    url = reverse("lists:item-check", args=[shopping.pk, item.pk])

    body = _login(client, alice).post(url, HTTP_HX_REQUEST="true").content.decode()

    assert 'id="shopping-actions"' in body
    actions = _actions_fragment(body)
    assert 'hx-swap-oob="true"' in body
    assert "Clear checked (1)" in actions


def test_unchecking_the_last_checked_item_drops_clear_checked_oob(client, shopping, alice):
    item = ListItem.objects.create(list=shopping, text="Bread", is_checked=True)
    url = reverse("lists:item-check", args=[shopping.pk, item.pk])

    body = (
        _login(client, alice)
        .post(url, {"is_checked": "false"}, HTTP_HX_REQUEST="true")
        .content.decode()
    )

    actions = _actions_fragment(body)
    assert "Clear checked" not in actions


def test_checking_the_last_unchecked_item_flips_to_uncheck_all_oob(client, shopping, alice):
    ListItem.objects.create(list=shopping, text="a", is_checked=True)
    last = ListItem.objects.create(list=shopping, text="b")
    url = reverse("lists:item-check", args=[shopping.pk, last.pk])

    body = _login(client, alice).post(url, HTTP_HX_REQUEST="true").content.decode()

    actions = _actions_fragment(body)
    assert ">Uncheck all</button>" in actions
    assert ">Check all</button>" not in actions
