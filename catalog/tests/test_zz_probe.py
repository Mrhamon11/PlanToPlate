"""REVIEWER PROBE — delete after review. Not part of the suite."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import Ingredient, Unit
from core.models import Visibility

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(user_factory):
    return user_factory(username="alice")


@pytest.fixture
def bob(user_factory):
    return user_factory(username="bob")


def client_for(user):
    c = APIClient()
    c.force_login(user)
    return c


def test_probe_public_filter_cannot_pull_private(alice, bob, make_ingredient):
    secret = make_ingredient(name="Alice Secret", owner=alice, visibility=Visibility.PRIVATE)
    r = client_for(bob).get("/api/ingredients/?public=true")
    print("PROBE public=true:", r.status_code, r.json())
    assert secret.pk not in [row["id"] for row in r.json()["results"]]


def test_probe_shared_holder_delete(alice, bob, make_ingredient):
    ing = make_ingredient(name="Shared Thing", owner=alice, visibility=Visibility.SHARED)
    ing.shared_with.add(bob)
    r = client_for(bob).delete(f"/api/ingredients/{ing.pk}/")
    print("PROBE shared-holder DELETE:", r.status_code)
    r2 = client_for(bob).patch(f"/api/ingredients/{ing.pk}/", {"name": "Hacked"}, format="json")
    print("PROBE shared-holder PATCH:", r2.status_code)
    r3 = client_for(bob).get(f"/api/ingredients/{ing.pk}/shares/")
    print("PROBE shared-holder GET /shares/:", r3.status_code)
    r4 = client_for(bob).post(
        f"/api/ingredients/{ing.pk}/share/", {"visibility": "PUBLIC"}, format="json"
    )
    print("PROBE shared-holder POST /share/:", r4.status_code)
    assert r.status_code == 403 and r2.status_code == 403
    assert r3.status_code == 403 and r4.status_code == 403


def test_probe_public_nonowner_write(alice, bob, make_ingredient):
    ing = make_ingredient(name="Public Thing", owner=alice, visibility=Visibility.PUBLIC)
    c = client_for(bob)
    print("PROBE public PATCH:", c.patch(f"/api/ingredients/{ing.pk}/", {"name": "x"}, format="json").status_code)
    print("PROBE public DELETE:", c.delete(f"/api/ingredients/{ing.pk}/").status_code)


def test_probe_system_ingredient_write(alice, make_ingredient, user_factory):
    staff = user_factory(username="staffy", is_staff=True, is_superuser=True)
    sys_ing = make_ingredient(name="System Salt")
    c = client_for(staff)
    print("PROBE staff PATCH system ing:", c.patch(f"/api/ingredients/{sys_ing.pk}/", {"name": "x"}, format="json").status_code)
    print("PROBE staff DELETE system ing:", c.delete(f"/api/ingredients/{sys_ing.pk}/").status_code)


def test_probe_shared_with_injection(alice, bob, make_ingredient):
    ing = make_ingredient(name="Mine", owner=alice, visibility=Visibility.PRIVATE)
    r = client_for(alice).patch(
        f"/api/ingredients/{ing.pk}/",
        {"shared_with": [bob.pk], "visibility": "PUBLIC", "is_system": True, "owner": bob.pk},
        format="json",
    )
    ing.refresh_from_db()
    print("PROBE injection PATCH:", r.status_code, r.json())
    print("  shared_with:", list(ing.shared_with.values_list("pk", flat=True)),
          "visibility:", ing.visibility, "is_system:", ing.is_system, "owner:", ing.owner_id)


def test_probe_convert_response_types(alice, gram, kilogram):
    import json
    r = client_for(alice).post(
        "/api/units/convert/",
        {"quantity": "1", "from_unit": kilogram.pk, "to_unit": gram.pk},
        format="json",
    )
    print("PROBE convert:", r.status_code, r.content)
    body = json.loads(r.content)
    print("  quantity repr:", repr(body["quantity"]), type(body["quantity"]))


def test_probe_convert_huge_and_bad(alice, gram, kilogram):
    c = client_for(alice)
    for q in ["9" * 40, "1e400", "NaN", "-5", "0.00000000000000001"]:
        r = c.post("/api/units/convert/", {"quantity": q, "from_unit": kilogram.pk, "to_unit": gram.pk}, format="json")
        print(f"PROBE convert quantity={q[:20]}:", r.status_code)


def test_probe_convert_foreign_private_ingredient(alice, bob, make_ingredient, gram, milliliter):
    ing = make_ingredient(
        name="Secret Oil", owner=alice, visibility=Visibility.PRIVATE,
        density_g_per_ml=Decimal("0.92"),
    )
    r = client_for(bob).post(
        "/api/units/convert/",
        {"quantity": "100", "from_unit": gram.pk, "to_unit": milliliter.pk, "ingredient": ing.pk},
        format="json",
    )
    print("PROBE convert foreign private ingredient:", r.status_code, r.content[:300])


def test_probe_unit_delete_in_use(user_factory, gram, make_ingredient):
    staff = user_factory(username="staffy2", is_staff=True)
    make_ingredient(name="Uses Gram")
    c = client_for(staff)
    try:
        r = c.delete(f"/api/units/{gram.pk}/")
        print("PROBE staff DELETE unit in use:", r.status_code)
    except Exception as exc:  # noqa: BLE001
        print("PROBE staff DELETE unit in use RAISED:", type(exc).__name__, exc)


def test_probe_unit_staff_mutate_system(user_factory, gram):
    staff = user_factory(username="staffy3", is_staff=True)
    r = client_for(staff).patch(f"/api/units/{gram.pk}/", {"to_base_factor": "5"}, format="json")
    gram.refresh_from_db()
    print("PROBE staff PATCH system unit:", r.status_code, "factor now", gram.to_base_factor)


def test_probe_quickadd_bad_unit_id(alice, gram):
    c = client_for(alice)
    try:
        r = c.post(reverse("catalog:ingredient-quick-add"), {"name": "Thing", "default_unit": "abc"})
        print("PROBE quickadd bad unit id:", r.status_code)
    except Exception as exc:  # noqa: BLE001
        print("PROBE quickadd bad unit id RAISED:", type(exc).__name__, exc)


def test_probe_quickadd_collides_with_case(alice, gram):
    Ingredient.objects.create(name="Flour", owner=alice, default_unit=gram, is_system=False)
    c = client_for(alice)
    r = c.post(reverse("catalog:ingredient-quick-add"), {"name": "  flour  "})
    print("PROBE quickadd case collide:", r.status_code, r.content[:200])
    print("  count:", Ingredient.objects.filter(owner=alice).count())


def test_probe_html_nonowner_write(alice, bob, make_ingredient, gram):
    ing = make_ingredient(name="Alice Public", owner=alice, visibility=Visibility.PUBLIC)
    c = client_for(bob)
    print("PROBE html GET edit (non-owner, visible):", c.get(reverse("catalog:ingredient-update", args=[ing.pk])).status_code)
    r = c.post(reverse("catalog:ingredient-update", args=[ing.pk]), {"name": "Hacked", "default_unit": gram.pk})
    print("PROBE html POST edit (non-owner):", r.status_code)
    ing.refresh_from_db()
    print("  name now:", ing.name)
    r2 = c.post(reverse("catalog:ingredient-delete", args=[ing.pk]))
    print("PROBE html POST delete (non-owner):", r2.status_code, "still exists:", Ingredient.objects.filter(pk=ing.pk).exists())


def test_probe_html_share_nonowner(alice, bob, make_ingredient):
    ing = make_ingredient(name="Alice Public2", owner=alice, visibility=Visibility.PUBLIC)
    c = client_for(bob)
    r = c.get(reverse("catalog:ingredient-share-modal", args=[ing.pk]))
    print("PROBE html share modal non-owner:", r.status_code, len(r.content))
    r2 = c.post(reverse("catalog:ingredient-share", args=[ing.pk]), {"visibility": "PRIVATE"})
    print("PROBE html share POST non-owner:", r2.status_code)
    ing.refresh_from_db()
    print("  visibility now:", ing.visibility)
    r3 = c.post(reverse("catalog:ingredient-unshare", args=[ing.pk]), {"users": [bob.pk]})
    print("PROBE html unshare POST non-owner:", r3.status_code)


def test_probe_html_share_system(alice, make_ingredient):
    sys_ing = make_ingredient(name="System Thing")
    c = client_for(alice)
    r = c.post(reverse("catalog:ingredient-share", args=[sys_ing.pk]), {"visibility": "PUBLIC"})
    print("PROBE html share POST on system row:", r.status_code)
    sys_ing.refresh_from_db()
    print("  visibility now:", sys_ing.visibility)


def test_probe_search_leak(alice, bob, make_ingredient):
    make_ingredient(name="Alice Ultra Secret", owner=alice, visibility=Visibility.PRIVATE)
    r = client_for(bob).get("/api/ingredients/?search=Ultra")
    print("PROBE search leak:", r.status_code, r.json())
    r2 = client_for(bob).get(reverse("catalog:ingredient-list"), {"search": "Ultra"})
    print("PROBE html search leak contains name:", b"Ultra Secret" in r2.content)


def test_probe_tag_filter_widen(alice, bob, make_ingredient, make_tag):
    t = make_tag("chicken")
    secret = make_ingredient(name="Alice Chicken", owner=alice, visibility=Visibility.PRIVATE)
    secret.tags.add(t)
    r = client_for(bob).get("/api/ingredients/?tags=chicken")
    print("PROBE tag filter:", r.status_code, r.json())


def test_probe_units_write_nonstaff(alice):
    c = client_for(alice)
    r = c.post("/api/units/", {"name": "z", "abbrev": "z", "dimension": "MASS", "to_base_factor": "1"}, format="json")
    print("PROBE non-staff POST unit:", r.status_code)
    r2 = c.post("/api/tags/", {"name": "zz", "kind": "DIET"}, format="json")
    print("PROBE non-staff POST tag:", r2.status_code)


def test_probe_unit_is_system_writable(user_factory, gram):
    staff = user_factory(username="staffy4", is_staff=True)
    r = client_for(staff).post(
        "/api/units/",
        {"name": "furlong", "abbrev": "fur", "dimension": "MASS", "to_base_factor": "1", "is_system": False},
        format="json",
    )
    print("PROBE staff create unit is_system=False:", r.status_code, r.content[:200])


def test_probe_anon(alice, make_ingredient):
    c = APIClient()
    print("PROBE anon list:", c.get("/api/ingredients/").status_code)
    print("PROBE anon convert:", c.post("/api/units/convert/", {}, format="json").status_code)
    print("PROBE anon quickadd:", APIClient().post(reverse("catalog:ingredient-quick-add"), {"name": "x"}).status_code)
