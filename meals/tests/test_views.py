"""HTML (HTMX) screens for dishes and recipe books (``Plan/06-Dishes-And-RecipeBooks/
test-plan.md``, "UI").

Covers the dish list / detail, the recipe-book detail grouping and touch reorder, the
"Add to book" control on the recipe page, and the large-book copy warning. The visibility
gates on these screens live in ``test_security.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from core.models import Visibility
from meals.models import Dish, RecipeBook, RecipeBookEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in(client, user_factory):
    user = user_factory(username="me")
    client.force_login(user)
    return client, user


# --- dish list ---------------------------------------------------------------------------


def test_dish_list_requires_login(client):
    response = client.get(reverse("meals:dish-list"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_dish_list_visibility(logged_in, alice, make_dish):
    client, me = logged_in
    make_dish(name="My Taco Night", owner=me, visibility=Visibility.PRIVATE)
    make_dish(name="Alice Secret Feast", owner=alice, visibility=Visibility.PRIVATE)

    content = client.get(reverse("meals:dish-list")).content.decode()

    assert "My Taco Night" in content
    assert "Alice Secret Feast" not in content


def test_dish_list_htmx_search_returns_fragment(logged_in, make_dish):
    client, me = logged_in
    make_dish(name="Taco Night", owner=me, visibility=Visibility.PRIVATE)
    make_dish(name="Sunday Roast", owner=me, visibility=Visibility.PRIVATE)

    response = client.get(reverse("meals:dish-list") + "?search=taco", HTTP_HX_REQUEST="true")

    content = response.content.decode()
    assert response.status_code == 200
    assert "<html" not in content
    assert "Taco Night" in content
    assert "Sunday Roast" not in content


# --- dish detail ------------------------------------------------------------------------


def test_dish_detail_404_for_invisible(logged_in, alice, make_dish):
    client, _me = logged_in
    dish = make_dish(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)
    assert client.get(reverse("meals:dish-detail", args=[dish.pk])).status_code == 404


def test_dish_detail_shows_combined_ingredients(
    logged_in, make_dish, make_recipe, make_ingredient, add_ingredient, add_component, gram
):
    client, me = logged_in
    tomato = make_ingredient("Tomato")
    salsa = make_recipe(name="Salsa", owner=me, visibility=Visibility.PRIVATE)
    add_ingredient(salsa, tomato, 300, gram)
    sauce = make_recipe(name="Sauce", owner=me, visibility=Visibility.PRIVATE)
    add_ingredient(sauce, tomato, 500, gram)
    dish = make_dish(name="Taco Night", owner=me, visibility=Visibility.PRIVATE)
    add_component(dish, salsa, servings="2", position=0)
    add_component(dish, sauce, servings="1", position=1)

    content = client.get(reverse("meals:dish-detail", args=[dish.pk])).content.decode()

    assert "Combined ingredients" in content
    assert "Salsa" in content and "Sauce" in content
    # 300 g x2 + 500 g x1 = 1100 g of Tomato, aggregated onto one line
    assert "1100" in content


def test_dish_made_and_favorite_use_requesters_stats(logged_in, make_dish):
    client, me = logged_in
    dish = make_dish(name="Chili Night", owner=me, visibility=Visibility.PRIVATE)

    client.post(reverse("meals:dish-made", args=[dish.pk]))
    client.post(reverse("meals:dish-favorite", args=[dish.pk]))

    from meals.models import DishStats

    stats = DishStats.objects.get(user=me, dish=dish)
    assert stats.times_made == 1
    assert stats.is_favorite is True


# --- dish form --------------------------------------------------------------------------


def test_dish_form_creates_with_components(logged_in, make_recipe):
    client, me = logged_in
    r1 = make_recipe(name="Rice", owner=me, visibility=Visibility.PRIVATE)
    r2 = make_recipe(name="Beans", owner=me, visibility=Visibility.PRIVATE)

    response = client.post(
        reverse("meals:dish-create"),
        {
            "name": "Rice and Beans",
            "description": "",
            "component_recipe": [str(r1.pk), str(r2.pk)],
            "component_servings": ["2", "1"],
        },
    )

    assert response.status_code == 302
    dish = Dish.objects.get(name="Rice and Beans")
    assert dish.owner == me
    assert [c.recipe_id for c in dish.components.all()] == [r1.pk, r2.pk]
    assert dish.components.get(recipe=r1).servings == Decimal("2")


def test_dish_form_rejects_invisible_recipe(logged_in, alice, make_recipe):
    client, me = logged_in
    secret = make_recipe(name="Alice Secret", owner=alice, visibility=Visibility.PRIVATE)

    response = client.post(
        reverse("meals:dish-create"),
        {"name": "Probe", "component_recipe": [str(secret.pk)], "component_servings": ["1"]},
    )

    assert response.status_code == 200  # re-rendered form with errors
    assert not Dish.objects.filter(name="Probe").exists()


def test_dish_form_rejects_zero_servings(logged_in, make_recipe):
    client, me = logged_in
    recipe = make_recipe(name="Rice", owner=me, visibility=Visibility.PRIVATE)

    response = client.post(
        reverse("meals:dish-create"),
        {"name": "Bad", "component_recipe": [str(recipe.pk)], "component_servings": ["0"]},
    )

    assert response.status_code == 200
    assert not Dish.objects.filter(name="Bad").exists()


def test_dish_form_creates_empty_dish(logged_in):
    """design.md "Edge cases": an empty dish is allowed to exist while being built. The form
    layer must not reject a submission with zero component rows.
    """
    client, me = logged_in

    response = client.post(
        reverse("meals:dish-create"),
        {"name": "Work in progress", "description": ""},
    )

    assert response.status_code == 302
    dish = Dish.objects.get(name="Work in progress")
    assert dish.owner == me
    assert dish.components.count() == 0


def test_dish_form_update_can_remove_all_components(
    logged_in, make_dish, make_recipe, add_component
):
    client, me = logged_in
    dish = make_dish(name="Shrinking", owner=me)
    add_component(dish, make_recipe(name="Rice", owner=me, visibility=Visibility.PRIVATE))
    assert dish.components.count() == 1

    response = client.post(
        reverse("meals:dish-update", args=[dish.pk]),
        {"name": "Shrinking", "description": ""},
    )

    assert response.status_code == 302
    assert dish.components.count() == 0


def test_dish_form_rejects_row_with_servings_but_no_recipe(logged_in):
    """The empty-dish loosening must not swallow a half-filled row: a servings value with no
    recipe is still a data-entry mistake.
    """
    client, me = logged_in

    response = client.post(
        reverse("meals:dish-create"),
        {"name": "Half a row", "component_recipe": [""], "component_servings": ["2"]},
    )

    assert response.status_code == 200
    assert not Dish.objects.filter(name="Half a row").exists()


def test_recipe_typeahead_filtered(logged_in, alice, make_recipe):
    """The dish form's recipe typeahead never surfaces an invisible recipe's name."""
    client, me = logged_in
    make_recipe(name="My Weeknight Pasta", owner=me, visibility=Visibility.PRIVATE)
    make_recipe(name="Pasta Alice Hides", owner=alice, visibility=Visibility.PRIVATE)

    content = client.get(
        reverse("meals:dish-recipe-options") + "?q=pasta", HTTP_HX_REQUEST="true"
    ).content.decode()

    assert "My Weeknight Pasta" in content
    assert "Pasta Alice Hides" not in content


# --- recipe book detail ---------------------------------------------------------------


def _recipe(me, make_recipe, name, **kw):
    return make_recipe(name=name, owner=me, visibility=Visibility.PRIVATE, **kw)


def test_book_detail_groups_by_section(logged_in, make_book, make_recipe):
    client, me = logged_in
    book = make_book(name="Weeknights", owner=me)
    quick = _recipe(me, make_recipe, "Quick Stir Fry")
    slow = _recipe(me, make_recipe, "Slow Braise")
    RecipeBookEntry.objects.create(book=book, recipe=quick, section="Fast", position=0)
    RecipeBookEntry.objects.create(book=book, recipe=slow, section="Weekend", position=0)

    content = client.get(reverse("meals:book-detail", args=[book.pk])).content.decode()

    assert "Fast" in content
    assert "Weekend" in content
    assert content.index("Fast") < content.index("Quick Stir Fry")


def test_book_add_and_remove_recipe(logged_in, make_book, make_recipe):
    client, me = logged_in
    book = make_book(name="Book", owner=me)
    recipe = _recipe(me, make_recipe, "Pancakes")

    client.post(
        reverse("meals:book-add-recipe", args=[book.pk]),
        {"recipe": str(recipe.pk), "section": "Breakfast"},
    )
    entry = RecipeBookEntry.objects.get(book=book, recipe=recipe)
    assert entry.section == "Breakfast"

    client.post(
        reverse("meals:book-remove-recipe", args=[book.pk, recipe.pk]),
        HTTP_HX_REQUEST="true",
    )
    assert not RecipeBookEntry.objects.filter(book=book, recipe=recipe).exists()


def test_book_add_recipe_owner_only(logged_in, alice, make_recipe):
    client, me = logged_in
    book = RecipeBook.objects.create(name="Alice Book", owner=alice, visibility=Visibility.SHARED)
    book.shared_with.add(me)
    recipe = _recipe(me, make_recipe, "Mine")

    response = client.post(
        reverse("meals:book-add-recipe", args=[book.pk]), {"recipe": str(recipe.pk)}
    )

    assert response.status_code == 403
    assert not RecipeBookEntry.objects.filter(book=book).exists()


def test_view_cannot_add_invisible_recipe_to_book(logged_in, alice, make_book, make_recipe):
    """The sneakiest read primitive in the app, through the HTML path this time."""
    client, me = logged_in
    book = make_book(name="My Book", owner=me)
    secret = make_recipe(name="Alice Secret", owner=alice, visibility=Visibility.PRIVATE)

    client.post(reverse("meals:book-add-recipe", args=[book.pk]), {"recipe": str(secret.pk)})

    assert not RecipeBookEntry.objects.filter(book=book).exists()


def test_book_detail_does_not_expand_invisible_recipe(logged_in, alice, make_book, make_recipe):
    """Defence in depth: an entry for a recipe the viewer cannot see is neither named nor
    counted on the book detail page (D31 unshare-a-child path).
    """
    client, me = logged_in
    book = make_book(name="Carol Book", owner=me)
    mine = _recipe(me, make_recipe, "Carol Own")
    hidden = make_recipe(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)
    RecipeBookEntry.objects.create(book=book, recipe=mine, section="")
    RecipeBookEntry.objects.create(book=book, recipe=hidden, section="")

    content = client.get(reverse("meals:book-detail", args=[book.pk])).content.decode()

    assert "Carol Own" in content
    assert "Alice Private" not in content
    assert "1 recipe" in content  # only the visible one is counted


def test_htmx_reorder_returns_fragment(logged_in, make_book, make_recipe):
    client, me = logged_in
    book = make_book(name="Book", owner=me)
    a = _recipe(me, make_recipe, "Aaa")
    b = _recipe(me, make_recipe, "Bbb")
    RecipeBookEntry.objects.create(book=book, recipe=a, section="", position=0)
    RecipeBookEntry.objects.create(book=book, recipe=b, section="", position=1)

    response = client.post(
        reverse("meals:book-entry-move", args=[book.pk, b.pk]),
        {"direction": "up"},
        HTTP_HX_REQUEST="true",
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "<html" not in content
    assert RecipeBookEntry.objects.get(book=book, recipe=b).position == 0
    assert RecipeBookEntry.objects.get(book=book, recipe=a).position == 1


def test_reorder_has_touch_buttons(logged_in, make_book, make_recipe):
    """Up/down controls are always present for a manually-ordered book — never drag-only
    (task 02 touch-parity rule).
    """
    client, me = logged_in
    book = make_book(name="Book", owner=me)
    for i in range(2):
        RecipeBookEntry.objects.create(
            book=book, recipe=_recipe(me, make_recipe, f"R{i}"), section="", position=i
        )

    content = client.get(reverse("meals:book-detail", args=[book.pk])).content.decode()

    assert 'aria-label="Move R0 up"' in content
    assert 'aria-label="Move R0 down"' in content


def test_book_ordering_selector_persists_default(logged_in, make_book, make_recipe):
    client, me = logged_in
    book = make_book(name="Book", owner=me)
    RecipeBookEntry.objects.create(
        book=book, recipe=_recipe(me, make_recipe, "Zed"), section="", position=0
    )

    response = client.post(
        reverse("meals:book-ordering", args=[book.pk]),
        {"ordering": "NAME"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    book.refresh_from_db()
    assert book.default_ordering == "NAME"


def test_book_ordering_get_does_not_persist(logged_in, make_book, make_recipe):
    """The ordering endpoint writes ``default_ordering``, so it must not be reachable by a
    GET — a cross-site ``<img src=".../ordering/?ordering=NAME">`` would otherwise flip a
    logged-in owner's stored preference (CSRF does not cover GET).
    """
    client, me = logged_in
    book = make_book(name="Book", owner=me, default_ordering="MANUAL")
    RecipeBookEntry.objects.create(
        book=book, recipe=_recipe(me, make_recipe, "Zed"), section="", position=0
    )

    response = client.get(
        reverse("meals:book-ordering", args=[book.pk]) + "?ordering=NAME",
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 405
    book.refresh_from_db()
    assert book.default_ordering == "MANUAL"


def test_book_ordering_post_ignored_for_non_owner(client, user_factory, make_book, make_recipe):
    """A viewer who is not the owner can preview an ordering but never persist it."""
    owner = user_factory(username="owner")
    viewer = user_factory(username="viewer")
    book = make_book(
        name="Shared Book",
        owner=owner,
        default_ordering="MANUAL",
        visibility=Visibility.PUBLIC,
    )
    RecipeBookEntry.objects.create(
        book=book, recipe=make_recipe(name="Zed", owner=owner, visibility=Visibility.PUBLIC)
    )
    client.force_login(viewer)

    response = client.post(
        reverse("meals:book-ordering", args=[book.pk]),
        {"ordering": "NAME"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    book.refresh_from_db()
    assert book.default_ordering == "MANUAL"


def test_book_ordering_form_posts_with_csrf(logged_in, make_book, make_recipe):
    """The rendered selector is a POST form carrying a CSRF token (the no-JS fallback path)."""
    client, me = logged_in
    book = make_book(name="Book", owner=me)
    RecipeBookEntry.objects.create(
        book=book, recipe=_recipe(me, make_recipe, "Zed"), section="", position=0
    )

    content = client.get(reverse("meals:book-detail", args=[book.pk])).content.decode()

    assert reverse("meals:book-ordering", args=[book.pk]) in content
    assert 'name="csrfmiddlewaretoken"' in content
    assert 'hx-post="' + reverse("meals:book-ordering", args=[book.pk]) + '"' in content


# --- 06.10: add to book from the recipe page ---------------------------------------------


def test_add_to_book_from_recipe_page(logged_in, make_book, make_recipe):
    client, me = logged_in
    recipe = _recipe(me, make_recipe, "Shakshuka")
    book = make_book(name="Brunch", owner=me)

    # the control is present on the recipe detail page
    detail = client.get(reverse("recipes:recipe-detail", args=[recipe.pk])).content.decode()
    assert "Add to book" in detail
    assert "Brunch" in detail

    response = client.post(
        reverse("meals:recipe-add-to-book", args=[recipe.pk]), {"book": str(book.pk)}
    )

    assert response.status_code == 302
    assert RecipeBookEntry.objects.filter(book=book, recipe=recipe).exists()


def test_add_to_book_rejects_other_users_book(logged_in, alice, make_recipe):
    client, me = logged_in
    recipe = _recipe(me, make_recipe, "Mine")
    alice_book = RecipeBook.objects.create(name="Alice Book", owner=alice)

    client.post(reverse("meals:recipe-add-to-book", args=[recipe.pk]), {"book": str(alice_book.pk)})

    assert not RecipeBookEntry.objects.filter(book=alice_book).exists()


# --- 06.11: large-book copy warning ----------------------------------------------------


def test_large_book_copy_warns(logged_in, alice, make_recipe):
    """The confirmation names the recipe count, and warns once it is large."""
    client, me = logged_in
    book = RecipeBook.objects.create(name="Big Book", owner=alice, visibility=Visibility.PUBLIC)
    for i in range(25):
        r = make_recipe(name=f"Public {i}", owner=alice, visibility=Visibility.PUBLIC)
        RecipeBookEntry.objects.create(book=book, recipe=r, position=i)

    content = client.get(
        reverse("meals:book-copy-confirm", args=[book.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()

    assert "25" in content  # names the count
    assert "a lot of recipes" in content.lower()


def test_small_book_copy_names_count_without_warning(logged_in, alice, make_recipe):
    client, me = logged_in
    book = RecipeBook.objects.create(name="Small", owner=alice, visibility=Visibility.PUBLIC)
    for i in range(3):
        r = make_recipe(name=f"P{i}", owner=alice, visibility=Visibility.PUBLIC)
        RecipeBookEntry.objects.create(book=book, recipe=r, position=i)

    content = client.get(
        reverse("meals:book-copy-confirm", args=[book.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()

    assert "all 3 recipes" in content
    assert "a lot of recipes" not in content.lower()


def test_book_copy_deep_copies(logged_in, alice, make_recipe):
    client, me = logged_in
    book = RecipeBook.objects.create(name="Src", owner=alice, visibility=Visibility.PUBLIC)
    r = make_recipe(name="Public Pie", owner=alice, visibility=Visibility.PUBLIC)
    RecipeBookEntry.objects.create(book=book, recipe=r, position=0)

    response = client.post(reverse("meals:book-copy", args=[book.pk]))

    assert response.status_code == 302
    mine = RecipeBook.objects.get(owner=me, copied_from=book)
    assert mine.entries.count() == 1
    assert mine.entries.get().recipe.owner == me


# --- book: remove-recipe confirm modal -------------------------------------------------


def test_book_remove_control_opens_confirm_modal(logged_in, make_book, make_recipe):
    """The x control is a styled #modal confirm (hx-get), never a raw hx-confirm prompt."""
    client, me = logged_in
    book = make_book(name="Book", owner=me)
    recipe = _recipe(me, make_recipe, "Pancakes")
    RecipeBookEntry.objects.create(book=book, recipe=recipe, section="")

    content = client.get(reverse("meals:book-detail", args=[book.pk])).content.decode()

    confirm_url = reverse("meals:book-remove-recipe-confirm", args=[book.pk, recipe.pk])
    assert f'hx-get="{confirm_url}"' in content
    assert 'hx-target="#modal"' in content
    assert "hx-confirm" not in content


def test_book_remove_confirm_modal_renders_for_htmx(logged_in, make_book, make_recipe):
    client, me = logged_in
    book = make_book(name="Weeknights", owner=me)
    recipe = _recipe(me, make_recipe, "Pad Thai")
    RecipeBookEntry.objects.create(book=book, recipe=recipe, section="")

    response = client.get(
        reverse("meals:book-remove-recipe-confirm", args=[book.pk, recipe.pk]),
        HTTP_HX_REQUEST="true",
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "<html" not in content
    assert "Pad Thai" in content
    assert "Weeknights" in content
    assert reverse("meals:book-remove-recipe", args=[book.pk, recipe.pk]) in content


def test_book_remove_confirm_forbidden_for_non_owner(client, user_factory, make_book, make_recipe):
    owner = user_factory(username="owner")
    viewer = user_factory(username="viewer")
    book = make_book(name="Shared", owner=owner, visibility=Visibility.SHARED)
    book.shared_with.add(viewer)
    recipe = make_recipe(name="Shared Recipe", owner=owner, visibility=Visibility.SHARED)
    recipe.shared_with.add(viewer)
    RecipeBookEntry.objects.create(book=book, recipe=recipe, section="")
    client.force_login(viewer)

    response = client.get(
        reverse("meals:book-remove-recipe-confirm", args=[book.pk, recipe.pk]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 403


def test_book_remove_confirm_404_for_invisible_book(logged_in, alice, make_recipe):
    client, me = logged_in
    book = RecipeBook.objects.create(name="Alice", owner=alice, visibility=Visibility.PRIVATE)
    recipe = make_recipe(name="R", owner=alice, visibility=Visibility.PRIVATE)
    RecipeBookEntry.objects.create(book=book, recipe=recipe, section="")

    response = client.get(
        reverse("meals:book-remove-recipe-confirm", args=[book.pk, recipe.pk]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 404


def test_book_remove_confirm_missing_entry_redirects(logged_in, make_book, make_recipe):
    client, me = logged_in
    book = make_book(name="Book", owner=me)
    recipe = _recipe(me, make_recipe, "Not Filed")

    response = client.get(reverse("meals:book-remove-recipe-confirm", args=[book.pk, recipe.pk]))

    assert response.status_code == 302
    assert response.url == reverse("meals:book-detail", args=[book.pk])

    # Under htmx the HtmxMiddleware rewrites the 302 to a 200 + HX-Redirect so the stale
    # dialog navigates the whole page rather than swapping book markup into #modal.
    htmx_response = client.get(
        reverse("meals:book-remove-recipe-confirm", args=[book.pk, recipe.pk]),
        HTTP_HX_REQUEST="true",
    )
    assert htmx_response.status_code == 200
    assert htmx_response["HX-Redirect"] == reverse("meals:book-detail", args=[book.pk])


def test_book_remove_confirm_post_drops_entry_and_swaps_sections(logged_in, make_book, make_recipe):
    client, me = logged_in
    book = make_book(name="Book", owner=me)
    keep = _recipe(me, make_recipe, "Keep Me")
    drop = _recipe(me, make_recipe, "Drop Me")
    RecipeBookEntry.objects.create(book=book, recipe=keep, section="Mains", position=0)
    RecipeBookEntry.objects.create(book=book, recipe=drop, section="Sides", position=0)

    response = client.post(
        reverse("meals:book-remove-recipe", args=[book.pk, drop.pk]),
        HTTP_HX_REQUEST="true",
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "<html" not in content
    assert not RecipeBookEntry.objects.filter(book=book, recipe=drop).exists()
    assert "Drop Me" not in content
    assert "Sides" not in content  # the emptied section is gone
    assert "Keep Me" in content
    # the confirm dialog dismisses itself in the same swap
    assert 'id="modal"' in content and 'hx-swap-oob="true"' in content


# --- share degradation ------------------------------------------------------------------


def test_dish_share_via_html_degrades_when_subtree_too_deep(
    logged_in, user_factory, make_dish, make_recipe, add_sub_recipe, add_component, cup
):
    """Sharing a dish walks ``walk_dependencies`` over its recipe's sub-tree. A recipe chain at
    the depth cap raises ``DepthExceededError`` (a ``GraphError``); the HTML share path must
    degrade like the REST ``share`` action (HTTP 400 there): redirect back with an error
    message, not a 500.
    """
    client, me = logged_in
    chain = [
        make_recipe(name=f"deep{i}", owner=me, visibility=Visibility.PRIVATE) for i in range(8)
    ]
    for parent, child in zip(chain, chain[1:], strict=False):
        add_sub_recipe(parent, child, 1, cup)
    dish = make_dish(name="Deep Dinner", owner=me)
    add_component(dish, chain[0])
    friend = user_factory(username="friend")

    response = client.post(
        reverse("meals:dish-share", args=[dish.pk]),
        {"visibility": "SHARED", "users": [friend.pk]},
    )

    assert response.status_code == 302
    assert response.url == reverse("meals:dish-detail", args=[dish.pk])
    error_messages = [m for m in get_messages(response.wsgi_request) if m.level_tag == "error"]
    assert error_messages, "expected an error message, not a 500"
    assert not Dish.objects.visible_to(friend).filter(pk=dish.pk).exists()
