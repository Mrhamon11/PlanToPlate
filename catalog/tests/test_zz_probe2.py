"""REVIEWER PROBE 2 — delete after review."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.services.units import convert
from core.models import Visibility

pytestmark = pytest.mark.django_db


def client_for(user):
    c = APIClient()
    c.force_login(user)
    return c


def test_probe_convert_precision(user_factory, cup, teaspoon, gram, milliliter):
    u = user_factory(username="p1")
    c = client_for(u)
    r = c.post(
        "/api/units/convert/",
        {"quantity": "0.3333333333", "from_unit": cup.pk, "to_unit": teaspoon.pk},
        format="json",
    )
    raw = r.content.decode()
    service = convert(Decimal("0.3333333333"), cup, teaspoon)
    print("PROBE service Decimal :", repr(service))
    print("PROBE wire JSON       :", raw)
    print("PROBE wire type       :", type(json.loads(raw)["quantity"]))
    print("PROBE equal?          :", Decimal(str(json.loads(raw)["quantity"])) == service)


def test_probe_share_modal_leak(user_factory, make_ingredient):
    alice = user_factory(username="alice2")
    bob = user_factory(username="bob2")
    carol = user_factory(username="carol2")
    ing = make_ingredient(name="Alice Pub", owner=alice, visibility=Visibility.PUBLIC)
    ing.shared_with.add(carol)
    body = client_for(bob).get(
        reverse("catalog:ingredient-share-modal", args=[ing.pk])
    ).content.decode()
    print("PROBE modal leaks carol?", "carol2" in body)
    print("PROBE modal leaks share form?", "share-form" in body)
    frag = client_for(bob).get(
        reverse("catalog:ingredient-share-modal", args=[ing.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()
    print("PROBE htmx modal leaks carol?", "carol2" in frag, "len", len(frag.strip()))


def test_probe_shareable_users_query(user_factory, make_ingredient, django_assert_num_queries):
    alice = user_factory(username="alice3")
    for i in range(5):
        user_factory(username=f"u{i}")
    ing = make_ingredient(name="Mine3", owner=alice, visibility=Visibility.PRIVATE)
    body = client_for(alice).get(
        reverse("catalog:ingredient-detail", args=[ing.pk])
    ).content.decode()
    print("PROBE detail page renders shareable_users inline?", "u0" in body)


def test_probe_quickadd_system_name(user_factory, make_ingredient, gram):
    """Quick-adding a name that already exists as a SYSTEM ingredient."""
    u = user_factory(username="p2")
    make_ingredient(name="Salt")
    c = client_for(u)
    r = c.post(reverse("catalog:ingredient-quick-add"), {"name": "Salt"})
    print("PROBE quickadd over system name:", r.status_code)
    print(r.content.decode()[:250])


def test_probe_quickadd_no_unit_at_all(user_factory):
    u = user_factory(username="p3")
    r = client_for(u).post(reverse("catalog:ingredient-quick-add"), {"name": "Thing"})
    print("PROBE quickadd with no units seeded:", r.status_code, r.content.decode()[:150])


def test_probe_list_queries(user_factory, make_ingredient, gram, make_tag,
                            django_assert_max_num_queries):
    u = user_factory(username="p4")
    t = make_tag("chicken")
    for i in range(20):
        ing = make_ingredient(name=f"Ing {i}", owner=u)
        ing.tags.add(t)
    c = client_for(u)
    from django.test.utils import CaptureQueriesContext
    from django.db import connection
    with CaptureQueriesContext(connection) as ctx:
        c.get(reverse("catalog:ingredient-list"))
    print("PROBE html list queries:", len(ctx))
    with CaptureQueriesContext(connection) as ctx2:
        c.get("/api/ingredients/")
    print("PROBE api list queries:", len(ctx2))


def test_probe_ingredient_create_api_ignores_extra(user_factory, gram):
    u = user_factory(username="p5")
    other = user_factory(username="p5b")
    r = client_for(u).post(
        "/api/ingredients/",
        {"name": "New", "default_unit": gram.pk, "owner": other.pk,
         "is_system": True, "visibility": "PUBLIC", "shared_with": [other.pk]},
        format="json",
    )
    print("PROBE create with injected fields:", r.status_code, r.content.decode()[:400])


def test_probe_tag_filter_dup(user_factory, make_ingredient, make_tag, gram):
    u = user_factory(username="p6")
    a = make_tag("a")
    b = make_tag("b")
    ing = make_ingredient(name="Both", owner=u)
    ing.tags.add(a, b)
    r = client_for(u).get("/api/ingredients/?tags=a&tags=b")
    print("PROBE tags OR dedupe:", r.status_code, r.json()["count"])


def test_probe_filter_unknown_param(user_factory, make_ingredient):
    u = user_factory(username="p7")
    make_ingredient(name="X", owner=u)
    r = client_for(u).get("/api/ingredients/?is_staple=notabool")
    print("PROBE is_staple=notabool:", r.status_code, r.content.decode()[:200])


def test_probe_unit_convert_incompatible_message(user_factory, gram, milliliter):
    u = user_factory(username="p8")
    r = client_for(u).post(
        "/api/units/convert/",
        {"quantity": "1", "from_unit": gram.pk, "to_unit": milliliter.pk},
        format="json",
    )
    print("PROBE incompatible:", r.status_code, r.content.decode())
