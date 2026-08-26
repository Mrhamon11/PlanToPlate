"""Plan/03-Ownership-And-Sharing/test-plan.md, "Serializers — core/tests/test_serializers.py"."""

from __future__ import annotations

import pytest
from rest_framework.test import APIRequestFactory

from core.models import Visibility
from core.tests.serializers import DummyNodeSerializer, DummySerializer

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()


def _request(user):
    django_request = _factory.post("/")
    django_request.user = user
    return django_request


def test_readonly_fields_enforced(alice, bob, carol, make_dummy):
    other = make_dummy(owner=bob)
    obj = make_dummy(owner=alice)
    serializer = DummySerializer(
        obj,
        data={
            "name": "renamed",
            "owner": carol.pk,
            "is_system": True,
            "shared_with": [bob.pk],
            "copied_from": other.pk,
        },
        context={"request": _request(alice)},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    for field in ("owner", "is_system", "shared_with", "copied_from"):
        assert field not in serializer.validated_data

    serializer.save()
    obj.refresh_from_db()

    assert obj.owner == alice
    assert obj.is_system is False
    assert obj.shared_with.count() == 0
    assert obj.copied_from is None
    assert obj.name == "renamed"


def test_owner_injected_from_request(alice, bob):
    serializer = DummySerializer(
        data={"name": "new dummy", "owner": bob.pk},
        context={"request": _request(alice)},
    )

    assert serializer.is_valid(), serializer.errors
    obj = serializer.save()

    assert obj.owner == alice


def test_visibility_is_read_only(alice, make_dummy):
    """Review finding (security #6): ``visibility`` must go through
    ``core.services.sharing.share()``/``set_visibility()`` (via ``/share/``), never a plain
    write on the base serializer — a second write path that skips the cascade check entirely.
    """
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)
    serializer = DummySerializer(
        obj,
        data={"visibility": Visibility.PUBLIC},
        context={"request": _request(alice)},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    assert "visibility" not in serializer.validated_data

    serializer.save()
    obj.refresh_from_db()
    assert obj.visibility == Visibility.PRIVATE


def test_nested_children_filtered_by_visibility(alice, carol, make_dummy_node):
    parent = make_dummy_node(owner=alice, name="parent", visibility=Visibility.PUBLIC)
    visible_child = make_dummy_node(owner=alice, name="visible", visibility=Visibility.PUBLIC)
    hidden_child = make_dummy_node(owner=alice, name="hidden", visibility=Visibility.PRIVATE)
    parent.depends_on.add(visible_child, hidden_child)

    serializer = DummyNodeSerializer(parent, context={"request": _request(carol)})

    assert serializer.data["depends_on"] == [visible_child.pk]
