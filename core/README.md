# `core` — Ownership & Sharing

This app is the ownership/visibility/sharing/copy machinery every user-creatable model in the
project inherits (`Plan/03-Ownership-And-Sharing/design.md`). It defines no concrete models of
its own — `OwnedModel` is abstract, and `core/tests/models.py`'s `DummyOwned`/`DummyNode`/
`DummyDivergentNode` exist only to let this app's own test suite exercise the machinery before
any real domain model existed.

**Read `Plan/03-Ownership-And-Sharing/design.md` for the *why* behind every rule below.** This
file is the *how*: the checklist for wiring a new model into it. Tasks 04 onward should be able
to follow this page without re-reading the design doc, though the design doc is where the
reasoning — and the edge cases — actually live.

## The rule that must never be broken

**Every queryset that can return user data goes through `.visible_to(user)`. Every write path
goes through `.editable_by(user)` or the `IsOwnerOrReadOnly` permission. Nobody ever hand-rolls
an ownership filter.** `Plan/ARCHITECTURE.md` calls this the single most
security-critical convention in the codebase, and it is enforced two ways:

1. `core/apps.py` registers a `manage.py check` (`core.E001`/`core.E002`) that fails the build if
   a concrete `OwnedModel` subclass is missing the owner-XOR-system constraint or overrides
   `objects` with something that isn't an `OwnedManager`.
2. `core/tests/test_conventions.py` fails the test suite if any registered viewset serving an
   `OwnedModel` doesn't mix in `OwnedViewSetMixin`, or if any `OwnedModel` subclass with a
   relation to another `OwnedModel` doesn't override `share_dependencies()`/`copy_children()`.

Both are regression guards, not substitutes for reading this checklist — they catch the mistake
after it's made; following the steps below is how you avoid making it.

## Making a new model owned: the checklist

Say you're adding `Recipe` in task 05. In order:

### 1. The model

```python
# recipes/models.py
from core.models import OwnedModel


class Recipe(OwnedModel):
    name = models.CharField(max_length=200)
    # ... your fields ...

    class Meta(OwnedModel.Meta):
        # Add your own Meta options here (ordering, indexes, ...) alongside OwnedModel.Meta's.
        pass
```

**Always subclass `OwnedModel.Meta`, never write a bare `class Meta:`.** Django does not merge
an abstract parent's `Meta` into a subclass automatically — a bare `class Meta:` silently drops
the owner-XOR-system `CheckConstraint` with no error at import time. `core.E001` catches this at
`manage.py check`, but don't rely on the safety net; write it right the first time.

If your subclass's `Meta` also needs its own `constraints` (a uniqueness rule, say), declaring
`constraints = [...]` **replaces** the inherited list rather than adding to it — write
`constraints = [*OwnedModel.Meta.constraints, YourConstraint(...)]` instead, or you've silently
dropped the owner-XOR-system check the same way a bare `class Meta:` does. `core.E001` catches
this too, but again: write it right the first time.

Do **not** override `objects` with a plain `models.Manager()`. `OwnedModel.objects` is already an
`OwnedManager` (built from `OwnedQuerySet` in `core/managers.py`), which is where
`.visible_to()`/`.editable_by()` live. If you need a custom manager for some other reason, build
it from `OwnedQuerySet` (`models.Manager.from_queryset(YourQuerySet)`) so the two capabilities
compose instead of one replacing the other. `core.E002` catches an outright replacement, but not
a custom manager that's merely missing the mixin.

Run `makemigrations` as usual — the check constraint and the M2M `shared_with` table come along
automatically from the abstract base.

### 2. Does this model contain other owned objects?

If `Recipe` can reference other `OwnedModel` instances (a `Dish` referencing `Recipe`s, a
`Recipe` referencing sub-`Recipe`s), override **both** hooks — always both together, never one
alone, since they can legitimately walk different edge sets (see `core/tests/models.py`'s
`DummyDivergentNode` for why the two are separate methods rather than one):

```python
class Dish(OwnedModel):
    def share_dependencies(self) -> list[OwnedModel]:
        """Every object this one references, whose read-access must cascade when this object
        is shared (design.md, "The cascade")."""
        return list(self.recipes.all())

    def copy_children(self, new_obj: "Dish", *, copier: Copier) -> None:
        """Deep-copy this object's children onto new_obj. Always go through
        copier.copy(dependency) — never call copy_object() directly — so the cycle guard,
        depth cap, and memoization (diamond-shaped graphs copied once, not once per path)
        apply."""
        new_recipes = [copier.copy(recipe) for recipe in self.recipes.all()]
        # ... re-attach new_recipes onto new_obj ...
```

If `Recipe` is a leaf (references no other owned object — most models, especially early ones,
will be), you don't need to override either hook; the inherited default (`[]` / no-op) is
correct and `test_all_owned_models_declare_hooks` will not ask you for anything.

**Exception — a leaf reached through the same join model as a real container.** The guard's
relation-walk also follows a plain, non-owned join model's *other* forward FK to see whether it
points at another `OwnedModel` (that's how it catches `Recipe` above, which only has a *reverse*
relation into `RecipeComponent`). That walk is symmetric: if `Ingredient` is the target of
`RecipeComponent.ingredient`, on the same join model whose `.recipe` FK points at `Recipe`, the
guard cannot tell `Ingredient` apart from a container — both FKs look identical from the walk's
point of view. It will flag `Ingredient` too, even though it's a genuine leaf.

If the guard flags a model you've confirmed has no owned children, do **not** silence it with a
no-op hook override — that reads identically to "I implemented this" whether you actually
investigated or just wanted the failure to stop. Instead declare the opt-out explicitly:

```python
class Ingredient(OwnedModel):
    contains_owned_children = False
```

This is a deliberate, reviewable, greppable statement, and it's checked before the heuristic
runs — the heuristic never gets a vote on a model that declares it either way. Reach for it only
after confirming the model really is a leaf; it's an escape hatch for a false positive the guard
cannot resolve on its own, not a way to skip investigating a hooks failure.

### 3. Serializer

```python
# recipes/serializers.py
from core.serializers import OwnedSerializer


class RecipeSerializer(OwnedSerializer):
    class Meta:
        model = Recipe
        fields = [
            "id",
            "name",
            "owner",
            "visibility",
            "shared_with",
            "is_system",
            "notes",
            "copied_from",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]
```

`OwnedSerializer` already makes `owner`, `is_system`, `shared_with`, `copied_from`, and
`visibility` read-only and injects `owner` from `request.user` on create — list them in
`Meta.fields` if you want them in the response, but never re-declare them as writable.
`visibility` is deliberately read-only even here: changing it goes through `/share/` (the
sharing service), which runs the cascade check a bare `PATCH` has no way to know about. Don't
add a writable `visibility` field to a subclass to "fix" this — that reopens the exact hole
`OwnedSerializer` closes.

**If your model has a relation to another `OwnedModel`** (per step 2), do not serialize it with
a bare `PrimaryKeyRelatedField`/nested serializer over the unfiltered relation — that leaks the
existence of a child the requester cannot see into a shared or public parent's response (design
doc "Security notes", #4). Filter it through `.visible_to()` yourself, e.g.:

```python
class DishSerializer(OwnedSerializer):
    recipes = serializers.SerializerMethodField()

    def get_recipes(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return list(obj.recipes.visible_to(user).values_list("pk", flat=True))
```

See `core/tests/serializers.py`'s `DummyNodeSerializer` for a worked, tested example of exactly
this pattern.

### 4. Viewset

```python
# recipes/api.py -- this project's convention for DRF viewsets (see accounts/api.py,
# Plan/05-Recipes/tasks.md); a plain "viewsets.py" works exactly the same, since
# test_all_owned_viewsets_use_visible_to discovers by URLconf, not by filename.
from rest_framework import viewsets
from core.viewsets import OwnedViewSetMixin


class RecipeViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = Recipe.objects.all()
    serializer_class = RecipeSerializer
```

`OwnedViewSetMixin` must come first in the MRO. It gives you, for free:

- `get_queryset()` routed through `.visible_to(request.user)` — never write your own
  `get_queryset()` that skips this; if you need to narrow further (e.g. an extra query param),
  call `super().get_queryset()` and filter *on top of* it, the same way
  `core/filters.py`'s `OwnedObjectFilterBackend` does.
- `get_permissions()` composing three layers, always additively: the project's
  `DEFAULT_PERMISSION_CLASSES` (read live from settings, not a stale import-time snapshot);
  this mixin's own action-keyed rule (`IsOwnerOrReadOnly` for plain CRUD, the stricter/looser
  rule the four extra actions below need); and, if your subclass declares its own
  `permission_classes`, or an `@action(...)` you add passes its own `permission_classes=[...]`
  kwarg, that declaration on top of both. An explicit declaration is *never* a substitute for
  the mixin's own per-action rule — only the project defaults and the mixin's rule ever run
  unconditionally, and your declaration adds to them. This is why `permission_classes =
  [IsAuthenticated]` on a subclass reads correctly as "require login" without also silently
  discarding `IsOwnerOrReadOnly`/`IsOwner`: it always tightens, never silently vanishes.
- `POST /recipes/{id}/share/`, `POST /recipes/{id}/unshare/`, `POST /recipes/{id}/copy/`,
  `GET /recipes/{id}/shares/` — wired to `core/services/sharing.py` and
  `core/services/copying.py`, with `GraphError`/`SharingError`/`CopyError` already mapped to a
  `400` with a message naming the blocking object, never a `500`.
- `?mine=true` / `?shared_with_me=true` / `?public=true` query filters
  (`core/filters.py`), each narrowing further on top of `.visible_to()`, never replacing it.

Register it with a router as usual (`config/urls.py` or an app-level `urls.py` included from
there) — `core/tests/test_conventions.py`'s `test_all_owned_viewsets_use_visible_to` discovers
your viewset by walking the resolved URLconf (`config.urls`) and reading `pattern.callback.cls`
off every route, so it finds your viewset the moment it's reachable at all, regardless of which
file it lives in — `viewsets.py`, `api.py` (this project's own precedent: `accounts/api.py`,
`Plan/04-Units-And-Ingredients/tasks.md`'s `catalog/api.py`, `Plan/05-Recipes/tasks.md`'s
`recipes/api.py`), or anywhere else. There is no separate registration step for the guard —
mounting the route is what makes it visible.

### 5. HTML views (if this model gets template-rendered screens)

```python
# recipes/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from core.mixins import OwnedObjectMixin, HtmxTemplateMixin


class RecipeListView(LoginRequiredMixin, OwnedObjectMixin, HtmxTemplateMixin, ListView):
    model = Recipe
    ...


class RecipeDetailView(LoginRequiredMixin, OwnedObjectMixin, DetailView):
    model = Recipe
    ...


class RecipeCreateView(LoginRequiredMixin, OwnedObjectMixin, CreateView):
    model = Recipe
    fields = [
        "name",
        "instructions",
        "yield_quantity",
        "yield_unit",
        ...,
    ]  # never owner/visibility/etc.

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)


class RecipeUpdateView(LoginRequiredMixin, OwnedObjectMixin, UpdateView):
    model = Recipe
    ...
```

`OwnedObjectMixin` goes first among core's own mixins (after `LoginRequiredMixin`, which is
this project's established convention — `core/views.py`'s `HomeView`, `accounts/views.py` —
since there is no global login-required middleware). It gives you the same two-layer defence
the API viewset has:

- `get_queryset()` routed through `.visible_to()` (an invisible object 404s before the view
  ever runs), and `get_object()` additionally checking `IsOwnerOrReadOnly` — the exact same
  permission class the API uses, not a re-derived HTML-side rule — so a GET (viewing, including
  viewing an edit form) succeeds for anyone who can see the object, but a POST (the only verb an
  HTML `<form>` sends; also covers an htmx `hx-put`/`hx-delete`) from a non-owner raises
  `PermissionDenied` → this project's styled 403 page. `ListView` only ever calls
  `get_queryset()` so the write check simply never triggers for it.
- `get_form_class()` refuses, with `ImproperlyConfigured`, a `CreateView`/`UpdateView` whose
  form exposes `owner`, `is_system`, `shared_with`, `copied_from`, or `visibility` as a
  writable field — the HTML counterpart of `OwnedSerializer` making those same fields read-only
  on the API side. **Never write `fields = "__all__"` on a form over an `OwnedModel`
  subclass** — list the real, safe fields explicitly, the same discipline `OwnedSerializer`'s
  `Meta.fields` already requires on the API side. Changing `visibility`/sharing must go through
  the `/share/` view or API action, never a plain form `POST`. Like `get_queryset()` above, this
  only runs if your own override calls `super().get_form_class()` — overriding the method
  outright bypasses it, the same way overriding `get_queryset()` without `super()` bypasses
  `visible_to()`.
- Nothing here sets `owner` for you on create — unlike `OwnedSerializer.create()`, a
  `CreateView` has no service-layer hook to inject it automatically, so `form_valid()` must set
  `form.instance.owner = self.request.user` before calling `super().form_valid(form)`, as
  above. Skipping this fails loudly (the owner-XOR-system `CheckConstraint` raises
  `IntegrityError`), not silently — but it's one line, so just write it.

### 6. UI partials

Four reusable partials exist under `templates/_partials/`, styled in
`static/css/components.css`:

- `_ownership_badge.html` — include with `object=...`. Renders Mine / Shared with me / Public /
  Built-in based on the object alone (no extra query — see the partial's own comment for why the
  four states are safe to treat as exhaustive once an object is already on-screen).
- `_copy_button.html` — include with `object=... copy_url=...`. Renders nothing if the viewer
  already owns the object; otherwise a form posting to the object's `/copy/` action.
- `_copied_from.html` — include with `object=...`. Renders "Copied from &lt;owner&gt;'s
  &lt;name&gt;." when `object.copied_from` is set (design.md, "UI": the provenance line), and
  nothing otherwise — including once the original has been deleted (`copied_from` is
  `SET_NULL`).
- `_share_modal.html` — include with `object=... share_url=... unshare_url=...
  shareable_users=... cancel_url=...`. **Self-defending, not just a caller contract**: the
  partial gates its own body on `user.is_authenticated and object.owner_id == user.id` and
  renders nothing at all for anyone else, since the current-shares list it displays is exactly
  as sensitive as the API's owner-only `/shares/` action (design.md: "the audience list is
  itself sensitive"). Still prefer offering the modal only to an owner in the first place
  (`_ownership_badge.html` tells you: only `Mine`) — the in-template gate is defence in depth,
  not a reason to skip that check at the call site.

`copy_url`/`share_url`/`unshare_url` are whatever URL your app wires to the corresponding
viewset action — there's no fixed name, since that depends on how you registered your router.

**Not yet wired for htmx**: `_share_modal.html` and `_copy_button.html` currently `POST` a plain
HTML form straight at the corresponding DRF action, which returns JSON (share) or a bare 204
(unshare/copy) — with no `hx-post`/`hx-target`/`hx-swap`, a real (non-htmx) form submission
navigates the browser to that raw response instead of back to a page. `_confirm_delete.html`'s
plain-form pattern doesn't have this problem because it posts to a Django view that redirects;
these two don't have an HTML view of their own yet to redirect to. Whoever wires the first real
screen against these partials needs to either add an HTML-view intermediary that redirects (the
`_confirm_delete.html` pattern) or add real `hx-post`/`hx-target`/`hx-swap` attributes and a
fragment response — don't copy the plain-form-to-JSON-endpoint shape as-is.

### 7. Tests

Write, at minimum, one test per section of
`Plan/03-Ownership-And-Sharing/test-plan.md` against your real model instead of the dummy
fixtures — the dummy-fixture suite under `core/tests/` proves the *machinery* is correct in the
abstract; it does not prove your model is wired to it correctly. In particular:

- The visibility matrix (owner/shared/public/system × visible/not) for your model's own list and
  detail endpoints.
- `test_unrelated_user_gets_404_not_403` for your model.
- If step 2 applies: a share/copy test proving the cascade actually reaches your model's real
  children, and that a foreign, ungrantable child refuses the whole operation with a message
  naming it.
- If step 3's nested-serializer note applies: a test proving an invisible child does not appear
  in a shared/public parent's serialized output.

You do not need to re-derive `test_conventions.py`'s two checks per model — they already run
against every installed app automatically. If they fail once your model lands, that is the
signal something above was skipped.

## Files in this app

| File | What it is |
|---|---|
| `core/models.py` | `Visibility`, `OwnedModel` |
| `core/managers.py` | `OwnedQuerySet` (`visible_to`/`editable_by`), `OwnedManager` |
| `core/permissions.py` | `IsOwnerOrReadOnly`, `IsOwner`, `CanCopy` |
| `core/services/graph.py` | `walk_dependencies` — the shared cycle-guarded, depth-capped traversal |
| `core/services/sharing.py` | `share`, `unshare`, `set_visibility` |
| `core/services/copying.py` | `copy_object`, `Copier` |
| `core/serializers.py` | `OwnedSerializer` |
| `core/viewsets.py` | `OwnedViewSetMixin` |
| `core/filters.py` | `OwnedObjectFilterBackend` (`?mine=`/`?shared_with_me=`/`?public=`) |
| `core/mixins.py` | `HtmxTemplateMixin`, `MessageMixin`, `OwnedObjectMixin` |
| `core/apps.py` | The `core.E001`/`core.E002` structural checks |
| `core/middleware.py` | `HtmxMiddleware` (request-flag + `HX-Boosted` + redirect→`HX-Redirect` rewrite) |
| `core/urls.py`, `core/views.py` | `core:home` and the app's other plain (non-owned) routes/views |
| `core/admin.py` | Admin registrations for this app (currently none — `OwnedModel` is abstract) |
| `templates/_partials/_ownership_badge.html`, `_copy_button.html`, `_copied_from.html`, `_share_modal.html` | The four reusable owned-object UI pieces |
