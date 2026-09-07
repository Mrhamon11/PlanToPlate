# 08 — Meal Planner · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

Generate a week of meals under user constraints, let the user adjust it by hand, and push the
resulting ingredients to a shopping list. The headline feature of the app.

**Depends on:** 07-Lists-And-Shopping.
**Enables:** N4.

## Models

```python
class MealPlanProfile(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="planner_profiles")
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)

    # gear 1
    days = models.PositiveSmallIntegerField(default=7)            # 1–7
    slots = models.JSONField(default=list)                        # ["DINNER"]
    # gear 2
    dish_template = models.CharField(choices=DishTemplate.choices, default=BALANCED)
    # gear 3
    source_scope = models.CharField(choices=SourceScope.choices, default=SHARED)  # MINE / SHARED / PUBLIC
    # gear 4
    tag_limits = models.JSONField(default=dict)                   # {"chicken": 1}
    # gear 5
    excluded_tags = models.ManyToManyField(Tag, related_name="excluded_by", blank=True)
    excluded_ingredients = models.ManyToManyField(Ingredient, blank=True)
    # gear 6
    no_repeat_days = models.PositiveSmallIntegerField(default=14)
    # gear 7
    min_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    favorites_only = models.BooleanField(default=False)
    favorites_bias = models.DecimalField(default=Decimal("1.5"), ...)
    # gear 8
    max_total_minutes = models.PositiveIntegerField(null=True, blank=True)


class MealPlan(OwnedModel):
    name = models.CharField(max_length=200)
    start_date = models.DateField()
    days = models.PositiveSmallIntegerField()
    profile = models.ForeignKey(MealPlanProfile, on_delete=models.SET_NULL, null=True)
    profile_snapshot = models.JSONField()          # the gears as actually used
    seed = models.BigIntegerField()
    shopping_list = models.ForeignKey("lists.List", on_delete=models.SET_NULL, null=True)


class MealPlanEntry(models.Model):
    plan = models.ForeignKey(MealPlan, on_delete=models.CASCADE, related_name="entries")
    day_index = models.PositiveSmallIntegerField()     # 0-based from start_date
    slot = models.CharField(choices=MealSlot.choices)
    dish = models.ForeignKey(Dish, on_delete=models.SET_NULL, null=True, blank=True)
    is_locked = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = [("plan", "day_index", "slot")]
```

### Why `seed` and `profile_snapshot`

**`seed`** (`MILESTONES.md` C9) makes generation reproducible. Without it the planner cannot
be tested at all — and an untestable generator at the heart of the app is where this project
would stall. It also gives the user "regenerate with the same settings but different luck"
(new seed) versus "rebuild exactly what I had" (same seed).

**`profile_snapshot`** records the gears as they actually were at generation time. Profiles get
edited; a plan should remain explicable six weeks later. It also means deleting a profile does
not orphan the history of why a plan looks the way it does.

### `is_locked`

The user pins the meals they like and regenerates the rest. This is what makes an imperfect
generator genuinely useful: nobody accepts a whole random week, but everybody accepts five out
of seven and re-rolls the other two.

## The generator — `planner/services/generate.py`

```python
@dataclass
class PlanResult:
    entries: list[MealPlanEntry]
    unfilled: list[tuple[int, str]]         # (day_index, slot)
    reasons: list[str]                      # human-readable, per unfilled slot
    seed: int
```

### Algorithm

**1. Build the candidate pool** — one query, honestly filtered:

- `Dish.objects.visible_to(user)` narrowed by `source_scope`.
- Drop dishes with no components.
- Drop anything carrying an `excluded_tag`, or containing an `excluded_ingredient`
  (checked through the flattened ingredient set, so an exclusion catches sub-recipes too —
  an allergy that only checks top-level ingredients is not an allergy filter).
- Apply `min_rating` / `favorites_only` against **the requesting user's** `DishStats`.
- Apply `max_total_minutes`.
- Apply `no_repeat_days` against `DishStats.last_made_at`.

**2. Weight** — favourites get `favorites_bias`; everything else 1.0.

**3. Fill each slot** in order, with `random.Random(seed)`:

- Locked entries stay and **still consume their tag budget**, or a lock plus a limit would
  double-count chicken. A locked entry reserves its dish and its tag budget **from any grid
  position, not only positions already passed** — otherwise a single-slot re-roll (which locks
  every other entry) can hand back a dish already used on a *later* day. Single-slot re-roll
  also excludes the slot's own current dish; if nothing else fits, the slot keeps its dish and
  the UI says so rather than silently changing nothing.
- Filter the pool by remaining `tag_limits` budget.
- For `BALANCED`, prefer dishes whose component roles cover protein + carb + vegetable; if none
  qualify, fall back to composing a dish from three separate recipes (below).
- For `ONE_POT`, prefer dishes containing an `ONE_POT`-role recipe.
- For `MIX`, alternate per the RNG. *(Implemented 08.4 rework: per-slot alternation between a
  `BALANCED` lean and a `ONE_POT` lean, starting phase drawn from the RNG. Each lean is a
  preference with fallback to any dish — unlike strict `BALANCED`, which has no fallback. If a
  finer definition was intended, revisit in 08.9+.)*
- Weighted-random pick, then decrement budgets and mark the dish used.

**4. Backtrack** — if a slot has no candidates, undo the previous slot's choice and retry with
it excluded. Bounded at 50 total backtracks; beyond that, leave the slot unfilled with a reason.

**5. Report honestly.** Never loop forever, never silently ignore a constraint the user set.
A partial plan that explains itself — "only 2 dishes tagged vegetable are available; you asked
for 7 days with no repeats" — is far more useful than a full plan that quietly dropped a rule.

### Composing a dish from recipes

The requirement: randomly select *recipes* to construct a dish (protein + carb + vegetable).
When no existing Dish fits a `BALANCED` slot, the generator composes one:

1. Pick a `PROTEIN`-role recipe, then `CARB`, then `VEGETABLE`, from `visible_to` candidates
   respecting the same exclusions and limits.
2. Build a **transient, unsaved** `Dish` named "Roast Chicken + Rice + Green Beans".
3. Persist it **only if the user keeps it** when saving the plan. Otherwise a few regenerations
   would litter the database with dozens of throwaway dishes nobody asked for.

Composed dishes are marked in the UI as auto-composed and offered a "save as a real Dish"
action.

## Shopping list generation

On save (or on demand):

```python
populate_shopping_list(
    lst=plan.shopping_list or get_or_create_default_shopping_list(user),
    dishes=[e.dish for e in plan.entries if e.dish],
    source_plan=plan,
    exclude_staples=profile.exclude_staples,
    replace_generated=True,
)
```

All the hard parts — flattening, sub-recipe yield scaling, aggregation, idempotent
regeneration — already live in tasks 05–07. This task only orchestrates. If this function
turns out to need new logic here, something was built in the wrong place.

Note (task 05 review): `FlatLine.from_recipes` is the full root→leaf recipe chain per line,
not just the recipe that directly lists the ingredient. The exclusion check
("checked through the flattened ingredient set") is unaffected, but any provenance display
built on it should account for the full chain.

## API

| Route | Notes |
|---|---|
| `GET/POST /api/planner/profiles/` | CRUD on the gears |
| `POST /api/planner/plans/generate/` | `{profile, start_date, seed?}` → a **preview**, unsaved |
| `POST /api/planner/plans/` | Persist a previewed plan |
| `GET/PATCH/DELETE /api/planner/plans/<id>/` | |
| `POST /api/planner/plans/<id>/share/` · `/unshare/` · `GET /shares/` | `OwnedViewSetMixin`; owner-only; read-only for the sharee. `copy` stays `405`. |
| `POST /api/planner/plans/<id>/regenerate/` | Respects `is_locked`; accepts a new seed |
| `PATCH /api/planner/plans/<id>/entries/<entry_id>/` | Manual swap, lock, clear |
| `POST /api/planner/plans/<id>/entries/<entry_id>/reroll/` | Re-roll one slot |
| `POST /api/planner/plans/<id>/generate-shopping-list/` | |
| `GET /api/planner/plans/<id>/preview-shopping-list/` | Ingredients without writing |

Generation is a **preview first**. Producing rows before the user has seen the plan means every
experiment leaves debris.

## UI

- **Profile editor** — the eight gears on one screen, grouped: *When* (days, slots), *What*
  (template, scope), *Limits* (tag limits, exclusions, no-repeat), *Quality* (rating,
  favourites, time). Sensible defaults so the first-time path is "pick 7 days, press Generate."
- **Generate screen** — profile picker, start date, Generate button, then a day-by-day grid.
- **Plan grid** — one card per day/slot: dish name, component recipes, time, a lock toggle, a
  re-roll button, and a manual-swap picker. Desktop shows a week grid; mobile stacks vertically.
- **Unfilled slots** are visually obvious and carry their reason inline — this is the thing
  that turns a frustrating failure into an actionable one. On a **saved** plan (which has no
  per-slot reason field — see `BACKLOG.md`) a **page-level banner** above the grid carries the
  aggregated reason(s), recomputed deterministically from the plan's own seed; a plan whose
  pool is effectively empty shows the empty-state guidance instead of a wall of blank cards.
- The **preview grid** links or names every dish the same way the saved grid does — a preview
  dish is always `visible_to` the requester by construction, so it must never render as
  "shared privately".
- **Shopping list preview** before writing, with a staples toggle. The toggle is tri-state-free
  — unchecking it explicitly *includes* staples; only an untouched control falls back to the
  profile / snapshot default.
- **Share** and **delete** controls on the saved-plan page, owner-only, using the same
  `_share_modal` / confirm-page patterns as dishes, books and recipes. A shared plan is
  read-only for the recipient (see "Security notes"). The planner index offers multi-select
  delete. *(11a — edit-share — lands with the future edit-share task; not built here.)*
- **Plan and profile cards** are clickable across their whole area, not just the title.

## Edge cases

- **Empty candidate pool** (a new user with no dishes): the whole plan is unfilled with the
  reason "You have no dishes yet — create one or copy a public one." The first-run experience
  must not be a blank grid with no explanation.
- Constraints stricter than the pool: partial plan, reason per slot.
- **Strict `BALANCED` has no dish-level fallback** (owner-confirmed, dev-test 2026-09-07). It
  selects only a dish covering protein + carb + vegetable, or composes one from recipes; a
  partial or one-pot dish is never substituted "close enough". Non-P/C/V shared/public dishes
  therefore surface only under `ONE_POT` / `MIX`. This is messaging, not a behaviour change —
  the profile form carries a one-line explainer under `dish_template`.
- `tag_limits` referencing a deleted tag: ignored, not an error.
- **Excluded tags** are matched against a dish's own `Dish.tags` only. A dish with no tags —
  including a materialised auto-composed dish — is not removed by "exclude every tag". This is
  intentional; excluded *ingredients* (checked through the flattened sub-recipe graph) are the
  allergy filter, excluded tags are a coarse dish-level preference.
- `no_repeat_days` excluding everything: detected and reported as the cause rather than
  presenting as an empty pool.
- All slots locked: regeneration is a no-op, reported as such.
- A locked entry whose dish is later deleted: `SET_NULL`, slot shows as empty and re-rollable.
- Two plans covering the same dates: allowed. Warn, do not block.
- `days` changed after generation: extra entries are created unfilled; removed days drop their
  entries after a confirmation.
- Generating with the same seed twice must produce **byte-identical** output.

## Security notes

- The candidate pool is built from `Dish.objects.visible_to(user)`. **A planner that suggests
  a dish you cannot see is a data leak wearing a friendly hat** — and it would be easy to write
  by starting from `Dish.objects.all()`. There is a dedicated test.
- `min_rating` and `no_repeat_days` read the *requesting user's* stats only.
- `profile_snapshot` is server-generated; a client cannot inject one.
- The seed is an integer, validated and bounded.
- Generation is bounded in time and backtracks: it must not become a CPU denial-of-service.
  Cap the pool query and the backtrack count.
- **Sharing a plan is read-only for the recipient and cascades read-grants to its scheduled
  dishes and their recipe graphs** (D44 re-decision, 08.20 B1 — reversing D44's original
  non-cascade clause; ARCHITECTURE.md decision-log write-up folded into 08.15). Cascade works
  exactly like sharing a `Dish`: `MealPlan.share_dependencies()` returns the entries' distinct
  dishes and `walk_dependencies` pulls their component recipes / sub-recipes / ingredients,
  and the share is **refused** — naming the blocking dish — if a scheduled dish the plan owner
  does not own is not already visible to the recipient. The sharee then reads the full week
  grid and can open every dinner in it, but gets no lock / re-roll / swap / regenerate /
  length / shopping-list control, and never sees the owner's `profile_snapshot` or profile
  name. Share / unshare are owner-only; unsharing does not cascade back (D31). The generated
  shopping list is **not** a share dependency — it is a separately-owned, separately-shared
  object, and deleting a plan removes its entries but not that list. Plan copy stays out of
  scope (`copy_children` is a documented no-op; `MealPlanViewSet.copy` is 405).
