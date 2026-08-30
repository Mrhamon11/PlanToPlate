# 04 — Units & Ingredients · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

The measurement system and the ingredient catalog — the vocabulary every recipe is written in.
First vertical slice: models, services, API, and screens.

**Depends on:** 03-Ownership-And-Sharing.
**Enables:** 05-Recipes and everything downstream.

## Units

The requirements asked for "many kinds of units" without saying what that means
(`MILESTONES.md` C3). Without structure, "2 cups + 200 g of flour" is unaddable and the
shopping list quietly produces nonsense.

```python
class Dimension(models.TextChoices):
    MASS = "MASS"; VOLUME = "VOLUME"; COUNT = "COUNT"

class Unit(models.Model):
    name = models.CharField(max_length=40, unique=True)     # "tablespoon"
    plural = models.CharField(max_length=40)                # "tablespoons"
    abbrev = models.CharField(max_length=12)                # "tbsp"
    dimension = models.CharField(choices=Dimension.choices, db_index=True)
    to_base_factor = models.DecimalField(max_digits=20, decimal_places=10)
    is_system = models.BooleanField(default=True)
```

Base units: **gram** (MASS), **millilitre** (VOLUME), **each** (COUNT). Every unit stores its
factor to its dimension's base, so conversion within a dimension is one multiply and one
divide, with no conversion table to maintain.

`Unit` is **not** an `OwnedModel`. Units are a shared vocabulary; letting each user define a
private "cup" would make shared recipes unreadable. New units are added by an admin.

Seeded units: g, kg, mg, oz, lb · ml, l, tsp, tbsp, cup, fl oz, pint, quart, gallon · each,
dozen, pinch, clove, slice, can, package.

> US customary is the default (the owner's context). Metric equivalents are seeded alongside,
> and every quantity displays in whatever unit it was entered — no silent normalisation. Users
> write "1 cup", not "236.588 ml".

### Conversion service — `catalog/services/units.py`

```python
def convert(quantity: Decimal, from_unit: Unit, to_unit: Unit,
            ingredient: Ingredient | None = None) -> Decimal
def to_base(quantity: Decimal, unit: Unit) -> Decimal
def humanize(quantity: Decimal, unit: Unit) -> str
```

- **Same dimension, MASS or VOLUME:** always works. `q * from.factor / to.factor`.
- **MASS ↔ VOLUME:** only when `ingredient.density_g_per_ml` is set. Otherwise raise
  `IncompatibleUnits`. **Never guess a density** — a wrong conversion produces a confidently
  incorrect shopping list, which is worse than a list that admits it has two separate lines
  for flour.
- **COUNT ↔ COUNT:** governed by `Unit.count_family` (D34). The **generic** family
  (`each`=1, `half dozen`=6, `dozen`=12) interconverts on real ratios via `to_base_factor`.
  Every packaging/piece unit (can, slice, clove, pinch, package, …) is its **own singleton
  family** and converts only to itself; any other COUNT↔COUNT pair raises `IncompatibleUnits`
  naming both units.
- **COUNT ↔ MASS/VOLUME:** never, even with a density set. "3 eggs" and "150 g" are only
  relatable through an ingredient-specific piece weight, which is out of scope.
- All arithmetic in `Decimal` with explicit quantisation. `0.1 + 0.2` in binary float is the
  reason.
- `humanize` renders "0.25 cup" as "¼ cup" — recipes are read by people, and decimals in a
  kitchen are friction.

## Tags

```python
class Tag(models.Model):
    name = models.CharField(max_length=40, unique=True)
    kind = models.CharField(choices=TagKind.choices)   # CUISINE | PROTEIN | DIET | FREEFORM
    slug = models.SlugField(unique=True)
```

Shared vocabulary like `Unit`, not owned. `kind` matters because the meal planner's tag limits
(gear 4) operate mainly on `PROTEIN` tags, and the UI groups the picker by kind.

Seeded: PROTEIN — chicken, beef, pork, fish, shellfish, egg, tofu, beans, lamb, turkey.
CUISINE — italian, mexican, chinese, indian, thai, japanese, french, greek, american, korean.
DIET — vegetarian, vegan, gluten-free, dairy-free, nut-free, low-carb.

## Ingredient

```python
class Ingredient(OwnedModel):
    name = models.CharField(max_length=120)
    default_unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    density_g_per_ml = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    is_staple = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, blank=True)
    # + owner, visibility, shared_with, notes, copied_from, is_system from OwnedModel
```

- `is_staple` — salt, pepper, oil, water. Excluded from generated shopping lists by default
  (`MILESTONES.md` §5), so the list is not 40% things already in the cupboard.
- `density_g_per_ml` — set on the seeded ingredients where it is well known (water 1.0, flour
  0.53, sugar 0.85, oil 0.92, honey 1.42). Null everywhere else, and null means "refuse to
  convert" rather than "assume 1.0".
- `tags` — the planner reads these for its limits and exclusions.
- Unique constraint on `(owner, lower(name))` for user ingredients, and on `lower(name)` for
  system ones, so one user cannot own two "Chicken Breast" rows. Cross-user duplication is
  allowed and expected.

### Seed data

~150 common ingredients as `is_system=True` fixtures across produce, proteins, dairy, grains,
canned goods, spices, and condiments — loaded by `manage.py seed_catalog`, which is
**idempotent** (match on name, update rather than duplicate) so it can be re-run after adding
to the fixture.

> Deferred to task 09 (noted as an open question in `MILESTONES.md` §8): letting an admin
> promote a user's ingredient to `is_system`, to stop fifteen users creating fifteen
> "Chicken Breast" rows. Not needed to ship this task.

## API

| Route | Notes |
|---|---|
| `GET /api/units/` | All units, filterable by `dimension`. Read-only. |
| `GET /api/tags/` | Filterable by `kind`. Read-only for non-staff. |
| `GET/POST /api/ingredients/` | List is `visible_to`; create sets owner from the request. |
| `GET/PUT/PATCH/DELETE /api/ingredients/<id>/` | Standard owned-object rules. |
| `POST /api/ingredients/<id>/copy/` | From `OwnedViewSetMixin`. |
| `POST /api/ingredients/<id>/share/` | |
| `GET /api/ingredients/?search=&tags=&is_staple=&mine=` | |
| `POST /api/units/convert/` | `{quantity, from_unit, to_unit, ingredient?}` → converted value or a 400 naming why it is impossible. |

`DELETE` on an ingredient in use by a recipe must fail with 409 and name the recipes — silent
cascade would gut people's recipes. Enforced by `on_delete=PROTECT` on `RecipeComponent`
(task 05), caught and translated to a helpful message.

## UI

- **Ingredient list** — search box (`hx-trigger="keyup changed delay:300ms"`), tag filter chips,
  staple toggle, ownership badges, paginated.
- **Ingredient form** — name, default unit (grouped by dimension), density with a "leave blank
  if unsure" hint, staple checkbox, tag picker, notes.
- **Quick-add** — an inline "＋ new ingredient" from inside the recipe editor (task 05) that
  posts a minimal ingredient and returns the new row, so writing a recipe is not interrupted
  by a full-page detour. Designed here, consumed there.
- **Unit picker** — a shared `_partials/_unit_select.html`, grouped by dimension, used by every
  quantity field in the app.

## Edge cases

- Deleting a unit that is in use: `PROTECT`. Units are admin-managed, so this is a guard rail
  rather than a user-facing flow.
- Ingredient named with different casing/whitespace: normalise on save for the uniqueness
  check; preserve what the user typed for display.
- Density of zero or negative: rejected by a validator. A zero density would divide by zero in
  conversion.
- Converting between the same unit: return the input unchanged without touching the factors.
- Very large or very small quantities: `Decimal` with generous precision; `humanize` falls back
  to decimals rather than absurd fractions.

## Security notes

- `Unit` and `Tag` writes are staff-only; the standard read-only viewset for everyone else.
- Ingredient endpoints inherit the full task 03 protection — nothing bespoke here, which is
  the point of having built task 03 first.
- `search` goes through the ORM's `icontains`. No raw SQL, no user string reaching a query
  as anything but a bound parameter.
- The seed command must never overwrite a user's ingredient with a system one — it matches on
  `is_system=True` only.
