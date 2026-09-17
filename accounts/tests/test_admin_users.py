"""User-management flows on the custom admin (task 09.5–09.8).

Covers the full "User management" table in ``Plan/09-Admin-Control-Center/test-plan.md``:
create-user temp passwords, the reset-password action, the delete-user preview + typed
confirmation + cascade, admin entitlement, and the last-admin guard on every route out.
"""

from __future__ import annotations

import io
import logging
from decimal import Decimal

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.sessions.models import Session
from django.urls import reverse

from accounts import services
from accounts.models import User
from catalog.models import Dimension, Ingredient, Unit
from lists.models import ItemSource, List, ListItem
from lists.signals import INGREDIENT_TOMBSTONE
from meals.models import Dish
from recipes.models import Recipe, RecipeComponent

pytestmark = pytest.mark.django_db


@pytest.fixture
def unit(db) -> Unit:
    return Unit.objects.create(
        name="gram",
        abbrev="g",
        plural="grams",
        dimension=Dimension.MASS,
        to_base_factor=Decimal("1"),
    )


@pytest.fixture
def admin_user(user_factory) -> User:
    return user_factory(username="rootadmin", is_staff=True, is_superuser=True)


@pytest.fixture
def admin_client(admin_user):
    from django.test import Client

    c = Client()
    c.force_login(admin_user)
    return c


def _create_url() -> str:
    return reverse("admin:accounts_user_create")


def _changelist_action(client, action: str, ids: list[int], **extra):
    return client.post(
        reverse("admin:accounts_user_changelist"),
        {"action": action, "_selected_action": [str(i) for i in ids], **extra},
    )


def _own_some_objects(owner: User, unit: Unit) -> None:
    for i in range(3):
        Recipe.objects.create(
            name=f"{owner.username} recipe {i}",
            instructions="x",
            yield_quantity=Decimal("1"),
            yield_unit=unit,
            owner=owner,
        )
    for i in range(2):
        Dish.objects.create(name=f"{owner.username} dish {i}", owner=owner)
    List.objects.create(name=f"{owner.username} list", owner=owner)


# --- 09.5 create user -----------------------------------------------------------------------


def test_create_user_generates_temp_password(admin_client):
    response = admin_client.post(
        _create_url(),
        {"username": "newbie", "email": "n@example.com", "first_name": "", "last_name": ""},
    )

    assert response.status_code == 200
    user = User.objects.get(username="newbie")
    assert user.must_change_password is True
    assert user.temp_password_expires_at is not None
    assert user.has_usable_password() is True


def test_temp_password_displayed_once(admin_client):
    response = admin_client.post(
        _create_url(), {"username": "shown", "email": "", "first_name": "", "last_name": ""}
    )
    body = response.content.decode()
    # The rendered page carries the plaintext exactly once, right after creation.
    assert 'id="temp-password"' in body
    shown = body.split('id="temp-password">', 1)[1].split("<", 1)[0].strip()
    assert shown
    assert User.objects.get(username="shown").check_password(shown)

    # A fresh GET of the create page never carries it again.
    reload = admin_client.get(_create_url())
    assert shown not in reload.content.decode()


def test_create_user_copy_button_has_clipboard_fallback(admin_client):
    """09 dev-test finding 3: a bare ``navigator.clipboard.writeText(...)`` throws silently
    over plain HTTP (no secure context) — self-hosted, non-TLS is this project's expected
    deployment. The Copy button must route through the feature-detecting helper (with an
    ``execCommand`` fallback) rather than calling the modern API directly, and the page must
    load that script and offer an on-page feedback slot.
    """
    response = admin_client.post(
        _create_url(), {"username": "copyfallback", "email": "", "first_name": "", "last_name": ""}
    )
    body = response.content.decode()

    assert "js/admin-copy.js" in body
    assert "ptpCopyToClipboard(" in body
    assert "navigator.clipboard.writeText(" not in body
    assert 'class="copy-feedback"' in body


def test_temp_password_not_stored(admin_client):
    response = admin_client.post(
        _create_url(), {"username": "nostore", "email": "", "first_name": "", "last_name": ""}
    )
    body = response.content.decode()
    shown = body.split('id="temp-password">', 1)[1].split("<", 1)[0].strip()

    user = User.objects.get(username="nostore")
    for field in user._meta.fields:
        value = getattr(user, field.name)
        if isinstance(value, str):
            assert shown not in value, field.name
    # ...and not on any LogEntry either.
    for entry in LogEntry.objects.all():
        assert shown not in entry.change_message
        assert shown not in entry.object_repr


def test_temp_password_not_logged(admin_client, caplog):
    with caplog.at_level(logging.DEBUG):
        response = admin_client.post(
            _create_url(), {"username": "nolog", "email": "", "first_name": "", "last_name": ""}
        )
    body = response.content.decode()
    shown = body.split('id="temp-password">', 1)[1].split("<", 1)[0].strip()

    assert shown not in caplog.text


def test_created_user_can_log_in_with_temp_password(admin_client, client):
    response = admin_client.post(
        _create_url(), {"username": "loginme", "email": "", "first_name": "", "last_name": ""}
    )
    shown = response.content.decode().split('id="temp-password">', 1)[1].split("<", 1)[0].strip()

    login_ok = client.post(reverse("accounts:login"), {"username": "loginme", "password": shown})
    assert login_ok.status_code in (301, 302)

    # Any app page now bounces to the forced-change screen.
    landed = client.get(reverse("core:home"))
    assert landed.status_code == 302
    assert landed.url == reverse("accounts:password_change")


def test_create_user_entitlement_logged_when_staff(admin_client):
    admin_client.post(
        _create_url(),
        {"username": "newstaff", "email": "", "first_name": "", "last_name": "", "is_staff": "on"},
    )
    user = User.objects.get(username="newstaff")
    assert user.is_staff is True
    messages = [e.change_message for e in LogEntry.objects.filter(object_id=str(user.pk))]
    assert any("Admin access granted" in m for m in messages)
    assert any("Temp password issued" in m for m in messages)


# --- 09.6 reset password --------------------------------------------------------------------


def test_reset_password_action(admin_client, user_factory):
    target = user_factory(username="resetme")
    old_hash = target.password

    response = _changelist_action(admin_client, "reset_temp_password", [target.pk])

    assert response.status_code == 200
    target.refresh_from_db()
    assert target.password != old_hash
    assert target.must_change_password is True
    assert target.temp_password_expires_at is not None
    shown = response.content.decode().split('class="temp-pw">', 1)[1].split("<", 1)[0].strip()
    assert target.check_password(shown)


def test_reset_invalidates_sessions(admin_client, user_factory, client):
    target = user_factory(username="sessiontarget")
    client.force_login(target)
    assert client.get(reverse("core:home")).status_code == 200
    old_key = client.session.session_key
    assert Session.objects.filter(session_key=old_key).exists()

    _changelist_action(admin_client, "reset_temp_password", [target.pk])

    assert not Session.objects.filter(session_key=old_key).exists()
    # The old session cookie no longer authenticates.
    assert client.get(reverse("core:home")).status_code == 302


def test_reset_password_copy_button_has_clipboard_fallback(admin_client, user_factory):
    """09 dev-test finding 3 (reset-password results page — same regression as the create-user
    page's Copy button)."""
    target = user_factory(username="resetcopyfallback")
    response = _changelist_action(admin_client, "reset_temp_password", [target.pk])
    body = response.content.decode()

    assert "js/admin-copy.js" in body
    assert "ptpCopyToClipboard(" in body
    assert "navigator.clipboard.writeText(" not in body
    assert 'class="copy-feedback"' in body


def test_reset_password_issue_logged(admin_client, user_factory):
    target = user_factory(username="loggedreset")
    _changelist_action(admin_client, "reset_temp_password", [target.pk])
    messages = [e.change_message for e in LogEntry.objects.filter(object_id=str(target.pk))]
    assert any("Temp password issued: admin reset" in m for m in messages)


# --- 09.7 delete user ---------------------------------------------------------------------


def _delete_url(user: User) -> str:
    return reverse("admin:accounts_user_delete", args=[user.pk])


def test_delete_preview_shows_counts(admin_client, user_factory, unit):
    victim = user_factory(username="victim")
    _own_some_objects(victim, unit)

    response = admin_client.get(_delete_url(victim))

    body = response.content.decode()
    assert response.status_code == 200
    assert "3 recipes" in body
    assert "2 dishs" in body or "2 dishes" in body
    assert "1 list" in body


def test_delete_requires_typed_confirmation(admin_client, user_factory, unit):
    victim = user_factory(username="typedconfirm")
    _own_some_objects(victim, unit)

    admin_client.post(_delete_url(victim), {"confirmation": "wrong"})

    assert User.objects.filter(pk=victim.pk).exists()
    assert Recipe.objects.filter(owner=victim).count() == 3


def test_delete_cascades_owned_objects(admin_client, user_factory, unit):
    victim = user_factory(username="cascades")
    _own_some_objects(victim, unit)

    admin_client.post(_delete_url(victim), {"confirmation": "cascades"})

    assert not User.objects.filter(pk=victim.pk).exists()
    assert not Recipe.objects.filter(name__startswith="cascades").exists()
    assert not Dish.objects.filter(name__startswith="cascades").exists()


def test_delete_preserves_others_copies(admin_client, user_factory, unit):
    author = user_factory(username="author")
    copier = user_factory(username="copier")
    original = Recipe.objects.create(
        name="Original",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=unit,
        owner=author,
    )
    copy = Recipe.objects.create(
        name="My copy",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=unit,
        owner=copier,
        copied_from=original,
    )

    admin_client.post(_delete_url(author), {"confirmation": "author"})

    copy.refresh_from_db()
    assert copy.copied_from is None
    assert Recipe.objects.filter(pk=copy.pk).exists()


def test_delete_user_tombstones_two_fk_generated_item(admin_client, user_factory, unit):
    """D41 reconciliation: a GENERATED ListItem carrying both ``ingredient`` and ``dish`` on a
    *bystander's* list. Both FKs point at the deleted user; the per-model ``pre_delete``
    receivers each skip it (the other FK is still set), so without the delete-user pre-pass the
    cascade nulls both and ``lists_listitem_has_content`` aborts the whole transaction.
    """
    author = user_factory(username="graphowner")
    bystander = user_factory(username="bystander")
    ingredient = Ingredient.objects.create(name="Shared ing", default_unit=unit, owner=author)
    dish = Dish.objects.create(name="Shared dish", owner=author)
    lst = List.objects.create(name="Bystander shopping", owner=bystander)
    item = ListItem.objects.create(
        list=lst, ingredient=ingredient, dish=dish, text="", source=ItemSource.GENERATED
    )

    admin_client.post(_delete_url(author), {"confirmation": "graphowner"})

    assert not User.objects.filter(pk=author.pk).exists()
    item.refresh_from_db()
    assert item.recipe_id is None and item.dish_id is None and item.ingredient_id is None
    # The line carried both ``ingredient`` and ``dish``; it represents an ingredient quantity,
    # so the ingredient label is the one stamped (09 review, non-blocking).
    assert item.text == INGREDIENT_TOMBSTONE


def test_delete_succeeds_when_self_owned_dish_component_protects_a_child(
    admin_client, user_factory, unit
):
    """D53 (``ARCHITECTURE.md``): a user's own recipe used in their own dish must not block
    deleting them — the ``DishComponent`` row is cascading away in the same operation
    (``dish__owner == recipe__owner == the departing user``), so the pre-pass deletes it
    outright ahead of the cascade rather than letting Django's collector see it as a blocker.
    """
    from meals.models import DishComponent

    owner = user_factory(username="selfownedash")
    recipe = Recipe.objects.create(
        name="Self recipe",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=unit,
        owner=owner,
    )
    dish = Dish.objects.create(name="Self dish", owner=owner)
    DishComponent.objects.create(dish=dish, recipe=recipe, servings=Decimal("1"), position=0)

    response = admin_client.post(_delete_url(owner), {"confirmation": "selfownedash"}, follow=True)

    assert response.status_code == 200
    assert not User.objects.filter(pk=owner.pk).exists()
    assert not Recipe.objects.filter(pk=recipe.pk).exists()
    assert not Dish.objects.filter(pk=dish.pk).exists()


def test_delete_succeeds_when_self_owned_recipe_component_ingredient_protects_a_child(
    admin_client, user_factory, unit
):
    """D53: a user's own recipe using their own ingredient must not block deleting them —
    mirrors the live dev-test repro ("DT Test Shortbread" using "DT Test Flour").
    """
    owner = user_factory(username="selfingredient")
    ingredient = Ingredient.objects.create(name="Self flour", default_unit=unit, owner=owner)
    recipe = Recipe.objects.create(
        name="Self shortbread",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=unit,
        owner=owner,
    )
    RecipeComponent.objects.create(
        recipe=recipe, ingredient=ingredient, quantity=Decimal("1"), unit=unit, position=0
    )

    response = admin_client.post(
        _delete_url(owner), {"confirmation": "selfingredient"}, follow=True
    )

    assert response.status_code == 200
    assert not User.objects.filter(pk=owner.pk).exists()
    assert not Recipe.objects.filter(pk=recipe.pk).exists()
    assert not Ingredient.objects.filter(pk=ingredient.pk).exists()


def test_delete_succeeds_when_self_owned_recipe_component_sub_recipe_protects_a_child(
    admin_client, user_factory, unit
):
    """D53: a user's own recipe using their own recipe as a sub-recipe must not block deleting
    them — the dev-test repro hit this independently of the ingredient case ("DT Test Cookie
    Plate" using "DT Test Shortbread" as a sub-recipe), confirming the bug was not limited to
    one ``PROTECT`` field.
    """
    owner = user_factory(username="selfsubrecipe")
    shortbread = Recipe.objects.create(
        name="Self shortbread",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=unit,
        owner=owner,
    )
    cookie_plate = Recipe.objects.create(
        name="Self cookie plate",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=unit,
        owner=owner,
    )
    RecipeComponent.objects.create(
        recipe=cookie_plate, sub_recipe=shortbread, quantity=Decimal("1"), unit=unit, position=0
    )

    response = admin_client.post(_delete_url(owner), {"confirmation": "selfsubrecipe"}, follow=True)

    assert response.status_code == 200
    assert not User.objects.filter(pk=owner.pk).exists()
    assert not Recipe.objects.filter(pk__in=[shortbread.pk, cookie_plate.pk]).exists()


def test_delete_neutralizes_bystander_dish_component_protect(admin_client, user_factory, unit):
    """D53 (owner-approved 2026-09-17, ``ARCHITECTURE.md``): User A owns Recipe X; User B put X
    in Dish Y via ``DishComponent.recipe`` (``on_delete=PROTECT``) while X was public. Deleting
    A must now *succeed* — the pre-pass neutralizes this cross-owner ``PROTECT`` rather than
    refusing — leaving B's dish and component intact with the reference nulled: graceful
    degradation (D31's pattern), not a silent, untracked drop of the component row.

    Supersedes the old ``test_delete_user_refused_when_bystander_object_protects_a_child`` (09
    review), whose refuse-and-message assertions no longer hold under the resolved D53 design.
    """
    from core.models import Visibility
    from meals.models import DishComponent

    author = user_factory(username="protectedauthor")
    bystander = user_factory(username="protectbystander")
    recipe_x = Recipe.objects.create(
        name="Public recipe X",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=unit,
        owner=author,
        visibility=Visibility.PUBLIC,
    )
    dish_y = Dish.objects.create(name="Bystander dish Y", owner=bystander)
    component = DishComponent.objects.create(
        dish=dish_y, recipe=recipe_x, servings=Decimal("2"), position=0
    )

    response = admin_client.post(
        _delete_url(author), {"confirmation": "protectedauthor"}, follow=True
    )

    assert response.status_code == 200
    assert not User.objects.filter(pk=author.pk).exists()
    assert not Recipe.objects.filter(pk=recipe_x.pk).exists()
    assert Dish.objects.filter(pk=dish_y.pk).exists()
    component.refresh_from_db()
    assert component.recipe_id is None
    assert component.dish_id == dish_y.pk
    assert component.servings == Decimal("2")


def test_delete_neutralizes_bystander_recipe_component_ingredient_protect(
    admin_client, user_factory, unit
):
    """D53: User A owns a public ``Ingredient``; User B's own recipe uses it. Deleting A must
    succeed, leaving B's recipe and component intact with ``ingredient`` nulled — and
    ``recipes.services.flatten.flatten`` must skip the tombstoned line rather than crash on it
    (the graceful-degradation tolerance the finding requires wherever components are read).
    """
    from core.models import Visibility
    from recipes.services.flatten import flatten

    author = user_factory(username="ingredientauthor")
    bystander = user_factory(username="ingredientbystander")
    ingredient = Ingredient.objects.create(
        name="Shared flour", default_unit=unit, owner=author, visibility=Visibility.PUBLIC
    )
    recipe = Recipe.objects.create(
        name="Bystander cookies",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=unit,
        owner=bystander,
    )
    component = RecipeComponent.objects.create(
        recipe=recipe, ingredient=ingredient, quantity=Decimal("2"), unit=unit, position=0
    )

    response = admin_client.post(
        _delete_url(author), {"confirmation": "ingredientauthor"}, follow=True
    )

    assert response.status_code == 200
    assert not User.objects.filter(pk=author.pk).exists()
    assert not Ingredient.objects.filter(pk=ingredient.pk).exists()
    assert Recipe.objects.filter(pk=recipe.pk).exists()
    component.refresh_from_db()
    assert component.ingredient_id is None
    assert component.sub_recipe_id is None
    assert component.quantity == Decimal("2")
    assert flatten(recipe) == []


def test_delete_neutralizes_bystander_recipe_component_sub_recipe_protect(
    admin_client, user_factory, unit
):
    """D53: User A owns a public recipe used by User B as a sub-recipe. Deleting A must
    succeed, leaving B's recipe and component intact with ``sub_recipe`` nulled.
    """
    from core.models import Visibility

    author = user_factory(username="subrecipeauthor")
    bystander = user_factory(username="subrecipebystander")
    sub = Recipe.objects.create(
        name="Shared marinara",
        instructions="x",
        yield_quantity=Decimal("4"),
        yield_unit=unit,
        owner=author,
        visibility=Visibility.PUBLIC,
    )
    parent = Recipe.objects.create(
        name="Bystander lasagna",
        instructions="x",
        yield_quantity=Decimal("1"),
        yield_unit=unit,
        owner=bystander,
    )
    component = RecipeComponent.objects.create(
        recipe=parent, sub_recipe=sub, quantity=Decimal("1"), unit=unit, position=0
    )

    response = admin_client.post(
        _delete_url(author), {"confirmation": "subrecipeauthor"}, follow=True
    )

    assert response.status_code == 200
    assert not User.objects.filter(pk=author.pk).exists()
    assert not Recipe.objects.filter(pk=sub.pk).exists()
    assert Recipe.objects.filter(pk=parent.pk).exists()
    component.refresh_from_db()
    assert component.sub_recipe_id is None
    assert component.ingredient_id is None


def test_delete_view_does_not_log_when_service_refuses(admin_client, user_factory, monkeypatch):
    """Concurrent-demotion race: the ``is_last_admin`` pre-check passes, but
    ``services.delete_user``'s own guard trips. No deletion ``LogEntry`` may be written before
    the service returns, and the admin sees the guard message rather than a 500 (09 rework,
    non-blocking B — ``log_deletion`` moved after ``delete_user``).
    """
    from django.contrib.admin.models import DELETION

    victim = user_factory(username="raced")

    def _raise(*args, **kwargs):
        raise services.LastAdminError(
            f"{victim.username} is the only active admin — concurrent demotion race."
        )

    monkeypatch.setattr(services, "delete_user", _raise)

    response = admin_client.post(_delete_url(victim), {"confirmation": "raced"}, follow=True)

    assert User.objects.filter(pk=victim.pk).exists()
    assert not LogEntry.objects.filter(action_flag=DELETION, object_id=str(victim.pk)).exists()
    assert b"only active admin" in response.content


def test_delete_view_logs_deletion_with_real_id_after_delete(admin_client, user_factory, unit):
    """The happy path still records a deletion ``LogEntry`` against the user's real id, now
    written only after ``services.delete_user`` returns.
    """
    from django.contrib.admin.models import DELETION

    victim = user_factory(username="loggeddelete")
    _own_some_objects(victim, unit)
    victim_pk = victim.pk

    admin_client.post(_delete_url(victim), {"confirmation": "loggeddelete"})

    assert not User.objects.filter(pk=victim_pk).exists()
    assert LogEntry.objects.filter(action_flag=DELETION, object_id=str(victim_pk)).exists()


def test_delete_shows_deletion_message_in_recent_activity(admin_client, user_factory):
    """09 dev-test finding 2: a user delete's dashboard "Recent admin activity" line must say
    what happened, not render blank. ``self.log_deletion()`` writes a stock ``LogEntry`` with
    ``action_flag=DELETION`` and an empty ``change_message``; the dashboard template must
    branch on ``entry.is_deletion`` rather than printing ``entry.get_change_message`` blindly.
    """
    victim = user_factory(username="deletedforlog")

    admin_client.post(_delete_url(victim), {"confirmation": "deletedforlog"})
    response = admin_client.get(reverse("admin:index"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "Deleted" in body
    assert "deletedforlog" in body


# --- 09.8 entitlement + last-admin guard --------------------------------------------------


def test_entitle_admin_sets_staff(admin_client, user_factory):
    target = user_factory(username="promoteme", is_staff=False)

    _changelist_action(admin_client, "grant_admin", [target.pk])

    target.refresh_from_db()
    assert target.is_staff is True
    messages = [e.change_message for e in LogEntry.objects.filter(object_id=str(target.pk))]
    assert any("Admin access granted" in m for m in messages)


def test_revoke_admin_clears_staff(admin_client, user_factory):
    keeper = user_factory(username="keeper", is_staff=True)  # keeps an admin around
    target = user_factory(username="demoteme", is_staff=True)

    _changelist_action(admin_client, "revoke_admin", [target.pk])

    target.refresh_from_db()
    assert target.is_staff is False
    assert keeper.is_staff is True


def test_last_admin_cannot_be_demoted(admin_client, admin_user, user_factory):
    User.objects.exclude(pk=admin_user.pk).update(is_staff=False)
    assert services.is_last_admin(admin_user)

    # via the service
    with pytest.raises(services.LastAdminError):
        services.set_entitlement(actor=admin_user, user=admin_user, is_staff=False)

    # via the change form
    response = admin_client.post(
        reverse("admin:accounts_user_change", args=[admin_user.pk]),
        {
            "username": admin_user.username,
            "is_active": "on",
            "is_superuser": "on",
            "last_login_0": "",
            "last_login_1": "",
            "date_joined_0": "2026-01-01",
            "date_joined_1": "00:00:00",
            "must_change_password": "",
            "initial-date_joined_0": "2026-01-01",
            "initial-date_joined_1": "00:00:00",
            # is_staff omitted -> unchecked
        },
    )
    admin_user.refresh_from_db()
    assert admin_user.is_staff is True
    assert response.status_code == 200  # re-rendered with the guard error
    assert b"only active admin" in response.content  # the guard's message, not an unrelated error


def test_last_admin_cannot_be_deleted(admin_client, admin_user, user_factory):
    User.objects.exclude(pk=admin_user.pk).update(is_staff=False)

    with pytest.raises(services.LastAdminError):
        services.delete_user(actor=admin_user, user=admin_user)

    response = admin_client.post(
        _delete_url(admin_user), {"confirmation": admin_user.username}, follow=True
    )
    assert User.objects.filter(pk=admin_user.pk).exists()
    assert b"only active admin" in response.content


def test_admin_cannot_view_existing_password(admin_client, user_factory):
    target = user_factory(username="hashhider")

    response = admin_client.get(reverse("admin:accounts_user_change", args=[target.pk]))

    body = response.content.decode()
    assert response.status_code == 200
    assert target.password not in body
    assert "pbkdf2" not in body


# --- 09 rework: password-setting routes + bulk delete ------------------------------------


def test_stock_password_change_route_is_disabled(admin_client, user_factory):
    """The stock ``admin:auth_user_password_change`` form sets an arbitrary, known password
    with no token revocation, no session kill, and no audit record — it must not be reachable
    (09 review, blocking). Password resets go through the ``reset_temp_password`` action only.
    """
    target = user_factory(username="pwtarget")
    old_hash = target.password
    url = reverse("admin:auth_user_password_change", args=[target.pk])

    get_response = admin_client.get(url)
    assert get_response.status_code == 302
    assert get_response.url == reverse("admin:accounts_user_changelist")

    post_response = admin_client.post(
        url, {"password1": "a-known-password-1", "password2": "a-known-password-1"}
    )
    assert post_response.status_code == 302
    target.refresh_from_db()
    assert target.password == old_hash
    assert target.check_password("a-known-password-1") is False


def test_bulk_delete_selected_action_not_offered(admin_client, user_factory):
    """``delete_selected`` skips the per-model preview and typed-username confirmation
    design.md requires for user deletion — it is removed from ``UserAdmin`` (09 review,
    non-blocking).
    """
    from django.contrib import admin as django_admin
    from django.test import RequestFactory

    victim = user_factory(username="notdeletable")
    request = RequestFactory().get("/")
    request.user = victim  # any user; get_actions does not gate on it here
    user_admin = django_admin.site._registry[User]
    assert "delete_selected" not in user_admin.get_actions(request)

    # And a direct POST of the action changes nothing — it is not a registered action.
    before = User.objects.count()
    _changelist_action(
        admin_client, "delete_selected", list(User.objects.values_list("pk", flat=True))
    )
    assert User.objects.count() == before


# --- bootstrap_admin audit (D26) --------------------------------------------------------


def test_bootstrap_admin_force_emits_audit(user_factory):
    from django.core.management import call_command

    existing = user_factory(username="admin", is_staff=False, is_superuser=False)
    call_command("bootstrap_admin", "--force", stdout=io.StringIO())

    entries = [e.change_message for e in LogEntry.objects.filter(object_id=str(existing.pk))]
    assert any("Temp password issued: bootstrap_admin --force" in m for m in entries)
    assert any("Admin access granted" in m for m in entries)
