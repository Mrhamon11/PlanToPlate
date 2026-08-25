"""The visibility keystone (design.md, "The visibility keystone"; MILESTONES.md section 4).

Every queryset that can return user data must go through ``visible_to()``; every write path
must go through ``editable_by()`` or the ``IsOwnerOrReadOnly`` permission (core/permissions.py).
Nobody hand-rolls an ownership filter anywhere else — a filter written twice is a filter that
will diverge exactly once, silently, in the direction of leaking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.db.models import Q

if TYPE_CHECKING:
    from core.models import OwnedModel

AnyUser = AbstractBaseUser | AnonymousUser | None


class OwnedQuerySet(models.QuerySet):
    def visible_to(self, user: AnyUser) -> OwnedQuerySet[OwnedModel]:
        """Every row ``user`` is allowed to *read*: their own, anything shared with them,
        anything public, and every system object.

        An anonymous user gets ``.none()`` rather than raising — a missing ``@login_required``
        then degrades to an empty list instead of a leak (design.md). ``user`` being ``None``
        (a service or management command with no request to hand over) degrades the same way,
        rather than raising ``AttributeError`` on ``None.is_authenticated``.

        ``.distinct()`` is required: the ``shared_with`` join can multiply a row once per
        matching grant. Dropping it produces duplicate results — the visible symptom — while
        the real cost is someone "fixing" that later by rewriting the filter and reopening the
        leak this method exists to close.
        """
        if not getattr(user, "is_authenticated", False):
            return self.none()

        # Local import: core.models imports OwnedManager (built from this queryset) at module
        # load time, so importing core.models here at module scope would be circular. By the
        # time this method actually runs, core.models is fully loaded.
        from core.models import Visibility

        return self.filter(
            Q(owner=user)
            | Q(visibility=Visibility.PUBLIC)
            | Q(shared_with=user)
            | Q(is_system=True)
        ).distinct()

    def editable_by(self, user: AnyUser) -> OwnedQuerySet[OwnedModel]:
        """Every row ``user`` may *write* to directly: only their own, and never a system
        object — even a superuser cannot get one through this method, only through the admin.
        """
        if not getattr(user, "is_authenticated", False):
            return self.none()
        return self.filter(owner=user, is_system=False)


OwnedManager = models.Manager.from_queryset(OwnedQuerySet)
