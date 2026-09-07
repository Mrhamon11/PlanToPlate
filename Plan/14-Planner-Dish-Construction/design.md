# 14 — Planner Dish Construction · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) and [`../ARCHITECTURE.md`](../ARCHITECTURE.md) before starting.**
> Update both when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

Let the meal planner build a dinner out of the user's **recipes** when they want it to, not
only pick a whole `Dish` someone already assembled — and keep those built dinners **out of the
database** until the user deliberately saves one.

Task 08 already composes a protein + carb + vegetable `Dish` from three recipes, but only as a
silent last-resort fallback for a `BALANCED` slot with no matching dish, and it **materialises
every composition into a permanent `Dish` row** the moment the plan is saved
(`planner/services/persist.py::_materialise_composed_dish`, `notes="Auto-composed by the meal
planner."`). This task turns that buried fallback into a first-class, user-controlled,
budgeted mechanism, extends it past `BALANCED`, and replaces auto-materialisation with an
explicit **"Save as dish"** action.

**Depends on:** 08-Meal-Planner (the generator, `MealPlan` / `MealPlanEntry` / `MealPlanProfile`),
and 06-Dishes-And-RecipeBooks (`Dish` / `DishComponent`, `Recipe.role`).
**Enables:** nothing. Leaf.

## Owner decisions (2026-09-07)

These were settled with the owner before the spec was written. They are binding; a deviation
stops for the owner.

1. **Replace, don't run in parallel.** *All* generator-composed dinners — the new opt-in ones
   **and** the existing `BALANCED` fallback — are now **temp dishes**. Nothing the generator
   builds ever auto-creates a `Dish` row. The only path to a real `Dish` is the user clicking
   **"Save as dish"** on a plan slot. `persist._materialise_composed_dish` is deleted.
2. **The count is a cap, plus today's fallback stays.** A new profile field
   `construction_slots` caps how many slots per week the *opt-in* construction path may fill.
   The existing uncapped `BALANCED`-with-no-dish fallback **still fires** regardless of that
   cap — it just produces a temp dish now instead of a materialised one.
3. **Construction style follows `dish_template`.** No new style knob. `BALANCED` composes a
   P+C+V trio (existing), `ONE_POT` composes around a single one-pot-role recipe (new), `MIX`
   alternates per slot (existing alternation logic). The generate-screen override is a count
   only.
4. **Per-slot RNG-mixed choice.** When the toggle is on and construction budget remains, a
   seeded per-slot coin flip decides whether the generator tries to *construct first* or pick
   a *real dish first* for that slot. Once the budget is spent, real dishes only (the uncapped
   `BALANCED` fallback aside).

## The 10th gear

`ARCHITECTURE.md` §5 caps the generator at **eight gears**, with `exclude_staples` an
acknowledged 9th (shopping-list option, D50). This task adds a **10th**, as one gear with two
fields:

```python
# MealPlanProfile — gear 9 (construction)
allow_dish_construction = models.BooleanField(default=False)
construction_slots = models.PositiveSmallIntegerField(
    default=0,
    validators=[MaxValueValidator(MAX_DAYS)],   # 0..7; 0 with the toggle on == off
)
```

Raising the cap from 9 to 10 is **a decision to record in `ARCHITECTURE.md`**, not a thing to
slip in — same rule the eight gears and `Recipe.role`'s value set live under. Rationale for
the log: construction is a genuinely distinct generator behaviour (it changes *what a slot can
contain*, not just *which dishes qualify*), it is off by default so the cap's "deliberately
small knob set" intent is preserved for the common path, and folding it into an existing gear
would overload `dish_template`'s meaning.

`build_profile_snapshot` records both fields, so a saved plan stays explicable after the
profile changes (D48 pattern). Snapshot key: `allow_dish_construction`, `construction_slots`.

## Temp dishes — the persistence change

`MealPlanEntry` gains two fields:

```python
composed_recipe_ids = models.JSONField(default=list, blank=True)  # ordered [recipe_pk, ...]
composed_name = models.CharField(max_length=200, blank=True)      # "Roast Chicken + Rice + Beans"
```

An entry is now one of **three** states, mutually exclusive:

| State | `dish` | `composed_recipe_ids` |
|---|---|---|
| Real dish | set | `[]` |
| Composed (temp) | `None` | non-empty |
| Unfilled | `None` | `[]` |

Enforced in `MealPlanEntry.clean()` and by every service write path. A DB `CheckConstraint` on
JSON emptiness is **not** portable across SQLite/Postgres the way the project requires
(`ARCHITECTURE.md` §2) — the invariant is service-layer + `clean()`, with a
`test_models.py` guard. If the reviewer wants a constraint, it must be written as
`Q(composed_recipe_ids=[])` and verified on both backends first.

**Why store the ids, not re-derive from the seed.** The generator is deterministic (C9), so
the composition *could* be reconstructed by re-running it. But D50 already made persist
stateless-by-re-running and the BACKLOG is full of the costs (`_add_unfilled_explanation`
re-runs the whole generator on a read path). A composed slot the user is about to save, lock,
or shop from needs to be *stable data*, not a recomputation. Storing the ordered recipe ids is
the same call `profile_snapshot` makes.

**`composed_name`** is stored at compose time for display stability; a regeneration rebuilds
it from the (possibly renamed) recipes. A component recipe later deleted or made invisible:
the slot renders degraded ("a recipe in this meal is no longer available") and stays
re-rollable — the `SET_NULL`-for-real-dishes behaviour, done by re-filtering
`composed_recipe_ids` through `Recipe.objects.visible_to(user)` at render time (security note
below).

## Generator changes — `planner/services/generate.py`

`generate_plan` gains one parameter:

```python
construction_slots: int | None = None
```

- `None` → derive: `profile.construction_slots if profile.allow_dish_construction else 0`.
- An explicit int (from the generate-screen override or the API) wins, **and enables
  construction for that run even if `allow_dish_construction` is off** — the user asking for
  "3 new dishes this week" on the generate screen is explicit consent. `0` disables it for the
  run.

In the slot-fill loop, for a non-locked cell:

1. **Coin flip** — only when `construction_budget_remaining > 0`. `rng` is consumed **only
   then**, so a plan that never enables construction keeps its exact task-08 RNG stream
   (byte-identical output is a hard test — the `mix_phase` line already establishes this
   "consume conditionally" pattern).
2. **Construct-first branch** — attempt `compose_*` for the slot's template. On success: place
   the temp dish, `constructions_used += 1`, continue. On `None`: fall through to real dishes
   (the RNG spent on the failed attempt is part of the deterministic stream, exactly as a
   `forbidden_signatures` rejection already is).
3. **Real-dish-first branch** (or fell through) — existing `_eligible` → `_weighted_pick`.
4. **Existing `BALANCED` fallback** — unchanged trigger (strict `BALANCED` slot, no real
   candidate), unchanged that it is **not** counted against `construction_slots`. It now
   produces a temp dish that persist stores rather than materialises.

`compose.py` grows:

- `build_one_pot_recipe_pool(user, profile)` — `Recipe.objects.visible_to(user).filter(role=ONE_POT)`,
  same exclusion filtering as `build_recipe_role_pools` (excluded tags; excluded ingredients
  through the flattened graph). Built once, lazily, like the P/C/V pools.
- `compose_one_pot_dish(pool, rng, *, avoid_recipe_ids, forbidden_signatures, max_total_minutes, tag_budget)`
  → an unsaved single-component `Dish` (`_composed_recipes = [recipe]`), or `None` under the
  same honest-degradation rules `compose_balanced_dish` uses. `forbidden_signatures` here is a
  set of single-id `frozenset`s.
- `MIX` construction reuses `_slot_template` alternation: a `MIX` slot leaning balanced calls
  `compose_balanced_dish`, leaning one-pot calls `compose_one_pot_dish`.

**Determinism, degradation, no-repeat-within-plan are all unchanged guarantees.** Composed
trios/singles still go through `forbidden_signatures` so a plan never repeats a composition,
and `total_minutes_for` still enforces gear 8.

**Locked composed slots on regeneration** (D50 parity): a locked composed entry is carried
through unchanged, keeps its `composed_recipe_ids` and `note`, its recipe tags still spend tag
budget (`_state_before` already reads `_composed_tags`), **and it seeds `constructions_used`**
— a locked composed slot consumes one construction-budget unit on the regeneration pass, the
same way a locked real dish consumes its tag budget.

## Persistence changes — `planner/services/persist.py`

- **`_materialise_composed_dish` is deleted.** `save_plan` / `update_plan_in_place` /
  `reroll_entry` no longer create `Dish` rows for composed slots.
- For a composed `PlanResult` entry (`is_composed(entry.dish)` true), persist writes
  `composed_recipe_ids = [r.pk for r in entry.dish._composed_recipes]` and
  `composed_name = entry.dish.name` onto the `MealPlanEntry`, with `dish=None`.
- `update_plan_in_place`: unlocked composed entries have their `composed_recipe_ids` rewritten
  in place; **locked entries stay completely untouched** (unchanged rule).
- `reroll_entry`: a re-roll may now return a composed result → store the ids; a re-roll that
  moves a slot *from* composed *to* a real dish clears `composed_recipe_ids` /
  `composed_name`; the "no other option, keep what's there" path is unchanged.
- Manual swap to a real dish (`MealPlanEntrySerializer.update`, `PlanEntrySwapView`) clears
  `composed_recipe_ids` and clears `is_locked` (D50 swap rule; an explicit `is_locked` in the
  payload still wins).

## "Save as dish" — `planner/services/materialise.py` (new)

```python
def save_composed_entry_as_dish(
    entry: MealPlanEntry,
    *,
    user: User,
    name: str,
    description: str = "",
    tag_ids: Sequence[int] = (),
) -> Dish: ...
```

- Refuses (`PlannerError` → 409) if `entry.dish_id` is already set — idempotent, not
  duplicating.
- Refuses if `entry.composed_recipe_ids` is empty, or if any referenced recipe is no longer
  `visible_to(user)` (the stored id is a snapshot; access can have changed).
- Creates `Dish(owner=user, visibility=PRIVATE, name=name, description=description)` +
  ordered `DishComponent`s (`servings=Decimal(1)` each, matching the old materialise), attaches
  `tag_ids` (each validated `visible_to` / system), points `entry.dish` at it, clears
  `composed_recipe_ids` / `composed_name`.
- **Owner-only** — `entry.plan.owner == user`. A sharee cannot save another user's composed
  slot as their own dish.

This is the *only* place a planner composition becomes a `Dish`. It replaces the marker-string
approach entirely, which retires the `is_auto_composed`-by-`notes`-equality BACKLOG item's
saved-plan half.

## Shopping list — orchestration only, unchanged principle

`planner/services/shopping.py::_planned_dishes` currently yields `entry.dish` per filled
entry. It now also yields, for each composed entry, a **transient `Dish`** built from
`composed_recipe_ids` (a `compose.transient_dish_from_ids(ids)` helper reusing
`_transient_dish`). `populate_shopping_list` / `preview_shopping_list` already flatten
transient composed dishes (task-08 preview path) — **no flatten / aggregate / scale logic is
added to `planner/`** (D50).

**Provenance regression, accepted:** `ListItem.dish` is an FK and a temp dish has no pk, so a
composed meal's aggregated ingredient lines carry **no contributing-dish provenance** —
`generated_from` (the plan) is the only "why is this here". Under the old auto-materialise this
line *did* get a real `ListItem.dish`. This is the cost of decision 1; record it as a D43
amendment.

## Sharing cascade — `MealPlan.share_dependencies()`

The generator composes from `Recipe.objects.visible_to(user)`, which includes recipes **shared
with** the plan owner — so a composed slot can reference a recipe the plan owner does not own.
Sharing the plan onward must cascade a read-grant to those recipes and their graphs, exactly
as it already does for scheduled dishes (D47).

`share_dependencies()` returns the entries' distinct dishes **plus** the distinct `Recipe`
objects referenced by composed entries' `composed_recipe_ids`. `walk_dependencies` then pulls
each recipe's sub-recipes / ingredients. `_validate_cascade` **refuses the share** — naming
the blocking recipe — if a composed recipe the plan owner does not own is not already visible
to the recipient. Unsharing does not cascade back (D31).

## API — `planner/api.py`, `planner/serializers.py`

| Route | Change |
|---|---|
| `GET/POST/PATCH /api/planner/profiles/` | `allow_dish_construction`, `construction_slots` (validate 0..7) in the serializer |
| `POST /api/planner/plans/generate/` | optional `construction_slots` override (int, 0..days) |
| `POST /api/planner/plans/<id>/regenerate/` | same optional `construction_slots` override |
| `POST /api/planner/plans/<id>/entries/<entry_id>/save-as-dish/` | **new.** Body `{name, description?, tags?}` → `201` with the created dish; `409` if the entry already has a dish; `403` for a non-owner. `IsOwner`, not `IsOwnerOrReadOnly` — a write on a sharee-visible plan. |
| `PATCH /api/planner/plans/<id>/entries/<entry_id>/` | setting `dish` clears `composed_recipe_ids` |

`MealPlanEntrySerializer` exposes: `composed_recipe_ids` (read-only), `composed_name`,
`is_composed` (true when `composed_recipe_ids` is non-empty **or** the transient-dish case),
and `component_recipes` — `[{id, name}]` resolved through `Recipe.objects.visible_to(request.user)`,
with `name` **nulled** for a recipe the viewer cannot see (D48 tombstoning parity — the raw id
is not dereferenceable, `/api/recipes/<id>/` is `visible_to`-scoped). The existing
`get_is_auto_composed` (which relies on `dish.pk is None`, so a *saved* composed slot
serialises as `false` today — a known BACKLOG bug) is fixed by this same field.

## UI — phone-first, no-JS parity (task 02 rule)

- **Profile editor** — a "Construct dishes from my recipes" checkbox and an "up to __ nights a
  week" number, in the *What* group directly under `dish_template`, with a one-line explainer:
  *"When on, the planner can build a meal from separate recipes — using the template above —
  instead of only choosing whole dishes you've saved."*
- **Generate screen** — a "New dishes this week" number field next to the existing days
  override. Empty = use the profile; `0` = none this run; `N` = up to N (and enables
  construction for the run). Hand-rolled to match the existing days field — the "make the
  generate screen a real `Form`" BACKLOG item is not in scope here; note it still stands.
- **Plan grid** — a composed slot card shows `composed_name`, lists each component recipe
  (linked), carries a small "composed" badge, and a **"Save as dish"** button.
  - **HTMX:** the button `hx-get`s a form fragment into `#modal` (D39 pattern — no
    `hx-confirm`); the form has name (prefilled from `composed_name`), a description textarea,
    and the shared tag multi-select from the dish form. It `POST`s with an explicit
    `hx-target` on the **slot card** (D39 corollary — never target the button), and the
    response swaps the card to a normal dish card and clears `#modal` via `hx-swap-oob`.
  - **No-JS:** the button is a real link to a standalone page
    `/planner/plans/<id>/entries/<entry_id>/save-as-dish/` that renders the same form
    full-page and `POST`s to the same view, redirecting back to the plan on success.
  - The old auto-composed label (`_slot_card.html` comparing `entry.dish.notes ==
    "Auto-composed by the meal planner."`) is **removed** — a saved plan no longer has
    auto-composed *dishes*, only composed *entries*, identified by `composed_recipe_ids`.

## Edge cases

- **Toggle on, `construction_slots = 0`** — construction is off. `0` is "never", not "unlimited".
- **Override set, profile toggle off** — construction runs for that generation only; the saved
  `profile_snapshot` records `allow_dish_construction: false` but the entries show what was
  built. `regenerate` without a fresh override falls back to the profile (off) — the composed
  slots then rebuild only via the uncapped `BALANCED` fallback, if applicable. Document this in
  the generate-screen help text.
- **Construction enabled but no role recipes** (`ONE_POT` template, user has no `ONE_POT`
  recipe) — the slot degrades to an explained unfilled entry, never a silent skip.
- **`construction_slots` larger than the number of slots** — harmless; the cap simply never
  bites.
- **A component recipe deleted after the plan is saved** — the composed slot renders degraded
  and re-rollable; `save_composed_entry_as_dish` refuses. The stale `composed_recipe_ids` is
  left in place (the row is still a valid degraded entry), same as a stale recently-viewed row.
- **Byte-identical output under a fixed seed** must still hold, with and without construction
  enabled.
- **Two slots composing the identical trio** — still prevented by `forbidden_signatures`; with
  a thin recipe library, one slot composes and the surplus slots go honestly unfilled (D49
  unchanged).

## Security notes

- **A composed slot must never surface a recipe the viewer cannot see** — the same data-leak
  rule as the dish pool. The generator already builds from `Recipe.objects.visible_to(user)`;
  the serializer and templates **re-filter `composed_recipe_ids` through
  `visible_to(request.user)` at render time** and tombstone the name of any recipe that no
  longer comes back. A sharee viewing a shared plan sees composed dinners only to the extent
  the cascade granted them the component recipes.
- **`save-as-dish` is owner-only** (`IsOwner`). A dedicated IDOR test: a sharee and a stranger
  both get `403`.
- **`construction_slots` is bounded** (0..7) and the coin-flip / compose attempts are inside
  the existing `MAX_BACKTRACKS`-bounded loop — construction must not become a CPU
  denial-of-service. A dedicated time-bound test with construction enabled against a hostile
  profile.
- **`profile_snapshot` stays owner-only on read** (D48) — the two new keys ride along.

## Carried-in findings

None. This task *retires* one BACKLOG item (the `is_auto_composed`-by-`notes`-string family)
and should check whether `compose_balanced_dish is single-shot against forbidden_signatures`
(BACKLOG, task 08 final review) is cheap to fix while `compose.py` is open — if so, do it; if
not, leave the BACKLOG line.
