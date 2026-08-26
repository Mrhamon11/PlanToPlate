"""Sharing service — the write path for visibility and ``shared_with`` grants (design.md,
"Sharing service"). Owner-only, cascades read-grants to every dependency the actor also owns,
and refuses — rather than partially applies — a share whose cascade would leave a recipient
unable to see a dependency that is not the actor's to grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.db import transaction

from core.models import Visibility
from core.services.graph import walk_dependencies

if TYPE_CHECKING:
    from core.models import OwnedModel


class SharingError(Exception):
    """A share was refused because its cascade would leave a target user unable to see a
    dependency the actor does not own (design.md, "The cascade"). Distinct from
    ``PermissionDenied``: this is a validation failure about the shape of the object graph, not
    about whether the actor is allowed to call ``share()`` at all.
    """


@dataclass
class ShareResult:
    obj: OwnedModel
    users: list[AbstractBaseUser]
    cascaded_to: list[OwnedModel]


def _require_can_manage_sharing(obj: OwnedModel, actor: AbstractBaseUser) -> None:
    if obj.is_system:
        raise PermissionDenied(f"{obj!r} is a system object and cannot be shared or unshared.")
    if obj.owner_id != actor.pk:
        raise PermissionDenied(
            f"Only the owner may share or unshare {obj!r}; sharing is a right of ownership, "
            "not of access."
        )


def _validate_visibility(visibility: str | None) -> None:
    """Guard the enforcement point itself, not just the API's request serializer — the HTMX
    caller (03.9/03.10) shares this service and must get the same protection without relying
    on a DRF ``ChoiceField`` existing on some other code path (MILESTONES.md section 6: "the
    REST API and the HTMX UI share the service layer").
    """
    if visibility is not None and visibility not in Visibility.values:
        raise SharingError(
            f"{visibility!r} is not a valid visibility — must be one of {Visibility.values}."
        )


def _validate_cascade(
    obj: OwnedModel,
    dependencies: list[OwnedModel],
    *,
    actor: AbstractBaseUser,
    users: list[AbstractBaseUser],
) -> None:
    for dependency in dependencies:
        if dependency.owner_id == actor.pk:
            continue
        manager = type(dependency)._default_manager
        for user in users:
            if not manager.visible_to(user).filter(pk=dependency.pk).exists():
                raise SharingError(
                    f"Cannot share {obj!s}: it contains {dependency!s}, which you do not own "
                    f"and which {user} cannot see. Make a copy of it first."
                )


def _validate_public_cascade(obj: OwnedModel, dependencies: list[OwnedModel]) -> None:
    """The PUBLIC-specific half of the cascade: widening ``obj`` to an audience of "everyone
    with an account" must not leave a foreign-owned dependency invisible to that same everyone.

    Without this, ``share(obj, visibility=PUBLIC)`` (or a bare ``set_visibility(..., PUBLIC)``)
    reaches the exact hollow-container state ``_validate_cascade`` exists to prevent for
    per-user shares, just by taking the wider, unchecked route: a foreign-owned dependency that
    is not itself ``PUBLIC`` or ``is_system`` cannot be granted to "everyone" by an actor who
    does not own it, so the whole change is refused, naming the blocking object.
    """
    for dependency in dependencies:
        if dependency.owner_id == obj.owner_id:
            continue
        if dependency.is_system or dependency.visibility == Visibility.PUBLIC:
            continue
        raise SharingError(
            f"Cannot make {obj!s} PUBLIC: it contains {dependency!s}, which you do not own "
            "and which is not visible to everyone. Make a copy of it first."
        )


def _cascade_grant_public(dependencies: list[OwnedModel], *, actor: AbstractBaseUser) -> None:
    """The other half of "actor-owned dependencies receive the equivalent grant": once a PUBLIC
    change is validated, every dependency the actor themself owns is widened to PUBLIC too, so
    a public Dish does not leave its owner's own private Recipes invisible underneath it.
    """
    for dependency in dependencies:
        if dependency.owner_id == actor.pk and dependency.visibility != Visibility.PUBLIC:
            dependency.visibility = Visibility.PUBLIC
            dependency.save(update_fields=["visibility"])


def share(
    obj: OwnedModel,
    *,
    actor: AbstractBaseUser,
    users: list[AbstractBaseUser] | None = None,
    visibility: str | None = None,
) -> ShareResult:
    """Grant ``users`` read access to ``obj`` and/or change its ``visibility``.

    Only ``obj.owner`` may call this (design.md: "a read-only holder cannot reshare"); a system
    object can never be shared or unshared. Sharing with ``actor`` themselves is silently
    dropped rather than erroring (design.md, "Edge cases").

    Every object ``obj`` transitively depends on (``walk_dependencies``, the same cycle guard
    and depth cap the copy service uses) that ``actor`` also owns is granted the same users. A
    dependency ``actor`` does not own must already be visible to every target user, or the
    whole share is refused with ``SharingError`` naming the blocking object — checked before any
    grant is written, so a refused share leaves no partial state.

    Widening ``visibility`` to ``PUBLIC`` runs the equivalent cascade check against "everyone"
    rather than a specific user list: every foreign-owned dependency must already be ``PUBLIC``
    or ``is_system``, and every actor-owned dependency is itself widened to ``PUBLIC`` so the
    now-public ``obj`` does not contain an invisible hole. This applies whether or not ``users``
    is also given — choosing the broader, no-named-recipient share is not a way around the
    per-user cascade check.
    """
    _require_can_manage_sharing(obj, actor)
    _validate_visibility(visibility)

    target_users = [user for user in (users or []) if user.pk != actor.pk]
    widening_to_public = visibility == Visibility.PUBLIC

    dependencies: list[OwnedModel] = []
    if target_users or widening_to_public:
        dependencies = walk_dependencies(obj)
    if target_users:
        _validate_cascade(obj, dependencies, actor=actor, users=target_users)
    if widening_to_public:
        _validate_public_cascade(obj, dependencies)

    cascaded_to = [dependency for dependency in dependencies if dependency.owner_id == actor.pk]

    with transaction.atomic():
        if target_users:
            obj.shared_with.add(*target_users)
            for dependency in cascaded_to:
                dependency.shared_with.add(*target_users)
        if visibility is not None:
            obj.visibility = visibility
            obj.save(update_fields=["visibility"])
        if widening_to_public:
            _cascade_grant_public(cascaded_to, actor=actor)

    return ShareResult(obj=obj, users=target_users, cascaded_to=cascaded_to)


def unshare(obj: OwnedModel, *, actor: AbstractBaseUser, users: list[AbstractBaseUser]) -> None:
    """Revoke ``users``' access to ``obj``.

    Does not cascade: revoking a container leaves its children's grants in place, since they
    may be load-bearing for a different object the recipient can still legitimately see
    (design.md, "Unsharing does not cascade").
    """
    _require_can_manage_sharing(obj, actor)
    if users:
        obj.shared_with.remove(*users)


def set_visibility(obj: OwnedModel, *, actor: AbstractBaseUser, visibility: str) -> None:
    """Change ``obj``'s visibility without touching ``shared_with`` — dropping from ``PUBLIC``
    to ``PRIVATE`` preserves any explicit grants already recorded (design.md, "Edge cases":
    "Only the public flag drops").

    Widening to ``PUBLIC`` runs the same cascade check ``share(..., visibility=PUBLIC)`` does
    (see its docstring) — this is the other write path to the same field, and the check must
    hold on both or it holds on neither.
    """
    _require_can_manage_sharing(obj, actor)
    _validate_visibility(visibility)

    widening_to_public = visibility == Visibility.PUBLIC
    dependencies: list[OwnedModel] = walk_dependencies(obj) if widening_to_public else []
    if widening_to_public:
        _validate_public_cascade(obj, dependencies)

    with transaction.atomic():
        obj.visibility = visibility
        obj.save(update_fields=["visibility"])
        if widening_to_public:
            owned_dependencies = [d for d in dependencies if d.owner_id == actor.pk]
            _cascade_grant_public(owned_dependencies, actor=actor)
