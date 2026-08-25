"""Plan/03-Ownership-And-Sharing/test-plan.md, "Model — core/tests/test_owned_model.py".

Exercises ``OwnedModel`` itself (03.1) against the throwaway ``DummyOwned`` fixture model —
defaults, the owner-XOR-system database constraint, the always-present ``notes`` field,
``copied_from`` provenance surviving the source's deletion, and cascade-delete of everything a
user owns.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from core.models import Visibility
from core.tests.models import DummyOwned

pytestmark = pytest.mark.django_db


def test_defaults_to_private(alice):
    obj = DummyOwned.objects.create(owner=alice)

    assert obj.visibility == Visibility.PRIVATE
    assert list(obj.shared_with.all()) == []


def test_owner_required_for_non_system(alice):
    """The design's CheckConstraint half: ``is_system=False`` demands a real ``owner``."""
    obj = DummyOwned(owner=None, is_system=False)

    with pytest.raises(IntegrityError), transaction.atomic():
        obj.save()


def test_system_object_must_have_no_owner(alice):
    """The other half of the XOR: an ``is_system`` row may not carry an ``owner``."""
    obj = DummyOwned(owner=alice, is_system=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        obj.save()


def test_system_object_with_no_owner_saves_cleanly():
    obj = DummyOwned.objects.create(owner=None, is_system=True)

    assert obj.pk is not None
    assert obj.owner is None


def test_notes_field_present(alice):
    """Every owned model carries free-form ``notes`` — easy to forget on model #6."""
    obj = DummyOwned.objects.create(owner=alice, notes="a private reminder")

    obj.refresh_from_db()
    assert obj.notes == "a private reminder"


def test_copied_from_set_null_on_source_delete(alice):
    original = DummyOwned.objects.create(owner=alice)
    copy = DummyOwned.objects.create(owner=alice, copied_from=original)

    original.delete()
    copy.refresh_from_db()

    assert copy.pk is not None
    assert copy.copied_from is None


def test_owner_cascade_deletes_objects(alice):
    obj = DummyOwned.objects.create(owner=alice)
    obj_pk = obj.pk

    alice.delete()

    assert not DummyOwned.objects.filter(pk=obj_pk).exists()
