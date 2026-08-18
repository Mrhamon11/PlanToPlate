# 03 — Ownership & Sharing · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

The ownership, visibility, sharing, and copy machinery that every domain model inherits. No
user-facing feature ships here — this task builds the thing that makes every later feature
safe.

**Depends on:** 00, 01, 02.
**Enables:** 04, 05, 06, 07, 08, N3.

> **This is the most security-critical task in the project.** A sharing model with per-object
> permissions is exactly the shape of application that leaks data through one forgotten
> queryset filter. The entire design here is aimed at making that mistake structurally hard
> rather than merely discouraged. Build it carefully; its test suite is deliberately the
> largest in the project.

## `OwnedModel`

An abstract base in `core/models.py`, inherited by `Ingredient`, `Recipe`, `Dish`,
`RecipeBook`, `List`, `MealPlan`, and later `Post`.

```python
class Visibility(models.TextChoices):
    PRIVATE = "PRIVATE", "Private"
    SHARED  = "SHARED",  "Shared with specific people"
    PUBLIC  = "PUBLIC",  "Everyone with an account"


class OwnedModel(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="%(class)ss", null=True, blank=True)
    visibility = models.CharField(max_length=16, choices=Visibility.choices,
                                  default=Visibility.PRIVATE, db_index=True)
    shared_with = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True,
                                         related_name="shared_%(class)ss")
    is_system = models.BooleanField(default=False, db_index=True)
    notes = models.TextField(blank=True)
    copied_from = models.ForeignKey("self", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="copies")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OwnedManager()

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=Q(is_system=True, owner__isnull=True)
                        | Q(is_system=False, owner__isnull=False),
                name="%(app_label)s_%(class)s_owner_xor_system",
            )
        ]
```

**Why a concrete M2M on an abstract base rather than a generic `Share` table.** The
`related_name="shared_%(class)ss"` pattern gives each concrete model its own join table. That
means real foreign keys, real indexes, and a plain `Q(shared_with=user)` in the visibility
filter. A single polymorphic `Share` table with a `ContentType` would need a subquery per model
and cannot be indexed as well — and this filter runs on every single request that touches user
data.

`owner` is nullable **only** for system objects, and the check constraint enforces the
exclusive-or at the database level. Application-level invariants that are not also database
constraints drift.

## The visibility keystone

```python
class OwnedQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(
            Q(owner=user)
            | Q(visibility=Visibility.PUBLIC)
            | Q(shared_with=user)
            | Q(is_system=True)
        ).distinct()

    def editable_by(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(owner=user, is_system=False)
```

**Rules, without exception:**

- Every queryset that can return user data goes through `.visible_to(user)`.
- Every write path goes through `.editable_by(user)` or the `IsOwnerOrReadOnly` permission.
- **Nobody hand-rolls an ownership filter in a view.** A filter written twice is a filter that
  will diverge exactly once, silently, in the direction of leaking.
- `.distinct()` is required — the M2M join multiplies rows. Forgetting it produces duplicate
  results, which is the symptom people notice; the real cost is that someone "fixes" it later
  by rewriting the filter.

An anonymous user gets `.none()` rather than an exception, so a missing `@login_required`
degrades to an empty list rather than a leak.

## Permissions

`core/permissions.py`:

- `IsOwnerOrReadOnly` — safe methods allowed if the object is visible; unsafe methods only for
  the owner, and never for `is_system` objects.
- `IsOwner` — owner only, for share/unshare endpoints.
- `CanCopy` — the object must be visible and **not** `PRIVATE`-and-not-yours. In practice, if
  you can see it, you can copy it; expressed explicitly so the rule is testable.

DRF's `get_object()` runs object permissions, but only over what `get_queryset()` returned —
which is why the queryset filter is the primary defence and the permission class is the
secondary one. Both, always.

## Sharing service

`core/services/sharing.py`

```python
def share(obj, *, actor, users=None, visibility=None) -> ShareResult
def unshare(obj, *, actor, users) -> None
def set_visibility(obj, *, actor, visibility) -> None
```

**Rules:**

1. Only `obj.owner` may share. A read-only holder cannot reshare — sharing is a right of
   ownership, not of access. Attempting it raises `PermissionDenied`.
2. `is_system` objects cannot be shared or unshared; they are already universally readable.
3. Sharing **cascades read-grants to referenced children.** Sharing a Dish grants read on its
   Recipes, their sub-Recipes, and their Ingredients.

### The cascade

This is the subtle part, and the requirements did not address it (see `MILESTONES.md` C5).
Without a cascade, a shared Dish arrives at the recipient with holes in it.

Each model that can contain others declares its children:

```python
class Dish(OwnedModel):
    def share_dependencies(self):
        return list(self.recipes.all())
```

The service walks the dependency graph transitively (with the same cycle guard the recipe
flattener uses) and, for every dependency **owned by the actor**, adds the same users to its
`shared_with`.

For a dependency **not owned by the actor** — a Recipe I copied from you and put in my Dish —
I cannot grant rights I do not hold. The service then checks whether the dependency is already
visible to each target user; if it is not, the share is **refused** with a message naming the
blocking object:

> "Cannot share 'Sunday Roast': it contains 'Nan's Gravy', which you do not own and which
> Bob cannot see. Make a copy of it first."

Refusing loudly beats sharing something broken. The suggested fix — copy the dependency —
resolves it, which is the whole reason the copy service exists.

**Unsharing does not cascade.** Revoking a Dish leaves the child grants in place. Auto-revoking
would silently break a *different* Dish the recipient can legitimately see. Revocation of
children is an explicit, separate action.

## Copy service

`core/services/copying.py`

```python
def copy_object(obj, *, actor, deep=True) -> OwnedModel
```

1. The object must be `.visible_to(actor)` — you cannot copy what you cannot see, which also
   means private objects are uncopyable by construction.
2. Create a new instance with `owner=actor`, `visibility=PRIVATE`, `is_system=False`,
   `copied_from=obj`, `shared_with` empty. **A copy is always private**, whatever the original
   was — inheriting a public visibility would silently republish someone else's work under
   your name.
3. Deep-copy children per each model's `copy_children(new_obj)` hook: a Dish copies its
   Recipes, a Recipe copies its Components (and recursively its sub-Recipes).
4. Per-user stats (`RecipeStats`, `DishStats`) are **not** copied. Your rating is yours; the
   copy starts with no history and `times_made=0`.
5. The whole thing runs in one `transaction.atomic()`. A half-copied Dish is worse than a
   failed copy.
6. Depth-capped and cycle-guarded, sharing the recipe traversal helper.

**Why deep and not by reference** (`MILESTONES.md` C6): a copy holding pointers into someone
else's rows breaks the moment they edit or delete. `copied_from` preserves the provenance link
for display ("copied from Alice's Roast Chicken") without creating the dependency.

Deduplication — noticing that the sub-recipe you are copying is byte-identical to one you
already own — is explicitly **out of scope**. It is a nice idea that turns into an identity
problem, and 20 users can tolerate some duplication.

## Deleting a user

Task 01 deferred this here. `owner` is `on_delete=CASCADE`: deleting a user deletes everything
they own.

This is the correct default for a 20-user personal app — the alternative, reassigning content
to a system owner, leaves orphaned data nobody maintains. But the admin UI (task 09) **must**
show a count of what will be destroyed and require confirmation. `copied_from` is
`SET_NULL`, so other people's copies survive with the provenance link cleared.

## API surface

Mixed into every owned resource's viewset via `OwnedViewSetMixin`:

| Route | Method | Notes |
|---|---|---|
| `/api/<resource>/<id>/share/` | POST | `{"users": [id], "visibility": "SHARED"}`. Owner only. |
| `/api/<resource>/<id>/unshare/` | POST | `{"users": [id]}`. Owner only. |
| `/api/<resource>/<id>/copy/` | POST | Returns the new object. |
| `/api/<resource>/<id>/shares/` | GET | Who can see it. **Owner only** — this list is itself sensitive. |

Query filters available on every owned list endpoint: `?mine=true`, `?shared_with_me=true`,
`?public=true`.

## UI

- A reusable share modal (`_partials/_share_modal.html`): visibility radio, user multi-select,
  current-shares list with revoke buttons.
- A "Copy to my collection" button on any object you do not own.
- A provenance line on copies: "Copied from Alice's Roast Chicken."
- An ownership badge — Mine / Shared with me / Public / Built-in.

## Edge cases

- Sharing with yourself: silently ignored, not an error.
- Sharing an already-`PUBLIC` object: allowed, no-op on visibility, still records the grants so
  that dropping back to `SHARED` preserves them.
- `PUBLIC` → `PRIVATE`: existing `shared_with` grants survive. Only the public flag drops.
- Deleting a shared object: it disappears for recipients. Their copies are unaffected.
- A user is deleted while holding shares: the M2M rows go with them.
- Copying an object that contains a sub-object you can see but whose *own* children you cannot:
  copy what is visible and fail loudly on the rest, rather than producing a hollow copy.

## Security notes

The threat model for this task, in priority order:

1. **IDOR.** Fetching another user's object by guessing its ID. Defence: the queryset filter,
   then the permission class. Tested on every verb of every endpoint.
2. **Enumeration.** A private object must return **404, not 403** — a 403 confirms the object
   exists, which is itself a leak. `.visible_to()` returning `.none()` produces this naturally.
3. **Privilege escalation via reshare.** A read-only holder attempting to share. Tested
   explicitly for every model.
4. **Leakage through relations.** A serializer that expands a sub-recipe the requester cannot
   see. Every nested serializer must filter through `.visible_to()`, and there is a test for it
   on every model with children.
5. **Mass-assignment of `owner`.** No serializer may accept `owner`, `is_system`, or
   `shared_with` as writable input. `owner` is set from `request.user`, server-side, always.
