# 09 — Admin Control Center · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

Everything an admin needs: user provisioning with temp passwords, direct table access, full
CRUD on every model, admin entitlement, password resets, and bulk JSON import.

**Depends on:** 08 (so every model exists to register).
**Enables:** 10.

## Approach: Django Admin, customized

`MILESTONES.md` D2. The requirements — "see the DB tables directly," "create, read, update and
delete entries in the DB for any table," "create users," "delete users" — describe Django Admin
almost exactly. Building it by hand would be weeks of re-implementing table browsing,
filtering, inline editing, and validation, and every hand-rolled admin is a fresh home for
authorization bugs.

What Django Admin does *not* give us, and this task adds:

1. Temp-password generation shown once to the admin.
2. Admin entitlement as a deliberate, audited action.
3. Password reset to a temp value.
4. Bulk JSON import.
5. A destructive-delete preview for users.

## Admin site configuration

A custom `AdminSite` (`config/admin.py`) with project branding and, importantly, an
`has_permission` that requires `is_staff` **and** `is_active` **and** not
`must_change_password`. An admin who has not yet completed a forced password reset should not
be administering anything.

Every model gets a `ModelAdmin` with `list_display`, `list_filter`, `search_fields`,
`readonly_fields` for computed values, `raw_id_fields` on high-cardinality relations, and
`list_select_related` to keep the changelist off N+1.

Inlines: `RecipeComponent` under `Recipe`, `DishComponent` under `Dish`, `ListItem` under
`List`, `MealPlanEntry` under `MealPlan`, `RecipeBookEntry` under `RecipeBook`.

**The recipe cycle guard must run in the admin too** (task 05 requires it on all three write
paths). `RecipeComponentInline` gets a `clean()` calling `assert_no_cycle`. An admin bypassing
the guard would create exactly the corrupt row the guard exists to prevent, and it would be
found much later, in the flattener.

## User management

A dedicated `UserAdmin` plus one purpose-built page, because these flows are frequent and the
generic admin form is a poor fit.

### Create user

Form: username, email, first/last name, `is_staff`. On save:

1. Generate a temp password via task 01's `generate_temp_password()`.
2. Create the user with `must_change_password=True` and a 7-day expiry.
3. **Display the temp password once**, on the success page, with a copy button and an explicit
   warning that it will not be shown again.
4. Never store it, never email it, never log it.

The requirement "admins should not be able to see actual passwords" is satisfied because this
is a *newly generated* value the admin is transmitting, not a stored one being revealed.

### Reset password

An admin action on selected users → new temp password, `must_change_password=True`, expiry
reset, **all their sessions invalidated**. Displayed once, as above.

Invalidating sessions matters: resetting a password because an account may be compromised is
pointless if the attacker's existing session survives.

### Delete user — with a preview

`owner` is `CASCADE` (`MILESTONES.md`, task 03), so deleting a user destroys everything they
own. The confirmation page **must show the count per model** — "This will permanently delete
34 recipes, 8 dishes, 3 books, 12 lists" — and require typing the username to confirm.

Django's stock delete confirmation lists objects individually, which is unreadable at 200 rows.
A summary count is what an admin can actually act on.

### Entitle as admin

A toggle setting `is_staff`. Guarded so that the last remaining admin cannot be demoted or
deleted — locking yourself out of a self-hosted app with no recovery path is a real, mundane
disaster.

## Bulk JSON import

The one genuinely custom piece. Available both as an admin page and as
`manage.py import_json <file> --owner <username>`.

### Format

```json
{
  "version": 1,
  "ingredients": [{"name": "...", "default_unit": "g", "tags": ["..."]}],
  "recipes": [{
    "name": "...", "yield_quantity": "4", "yield_unit": "serving",
    "instructions": "...", "role": "PROTEIN",
    "components": [{"ingredient": "Flour", "quantity": "2", "unit": "cup"}]
  }],
  "dishes": [{"name": "...", "recipes": ["..."]}]
}
```

References are **by name, resolved within the import and then against existing visible
objects.** Requiring database IDs would make hand-written import files impossible, and
hand-writing them is the main use case.

### Rules

1. **Validate everything before writing anything.** A whole-file dry run first, then one
   atomic transaction. A half-applied import is a mess an admin must untangle by hand.
2. Report every error with a JSON path — `recipes[3].components[1].unit: unknown unit 'cupp'`.
   A bare "invalid file" is unusable against a 400-line import.
3. `--owner` sets the owner; it defaults to the importing admin. **The importer may never set
   `owner` from inside the file** — that is a privilege escalation and an attribution forgery.
4. Caps: 5 MB file, 1000 objects, nesting depth 10. Enforced before parsing where possible.
5. Cycle guard applies to imported recipes.
6. `--dry-run` prints what would be created without writing.
7. Idempotency: `--skip-existing` (default) or `--update-existing`, matching on
   `(owner, name)`.

## Admin dashboard

A landing page with: user count, object counts per model, recent signups, database file size
and WAL size (an operational signal on SQLite), last backup timestamp (task 10), and quick
links to the frequent actions.

## Audit trail

Django's `LogEntry` covers admin CRUD. Add explicit `LogEntry` records for the custom actions —
temp password issued, admin entitlement changed, bulk import run — since these are precisely
the actions worth being able to reconstruct later. Log *that* a password was issued, never the
password.

## Edge cases

- The last admin demoting or deleting themselves: blocked with an explanation.
- Import referencing an unknown unit or tag: fails validation naming the path; never
  auto-creates units, since a typo would silently pollute the shared vocabulary.
- Import creating a recipe whose sub-recipe appears later in the file: two-pass resolution
  handles forward references.
- Import with a duplicate name in-file: rejected as ambiguous.
- Deleting a user who owns objects other users have *copied*: copies survive with
  `copied_from` nulled (task 03).
- Admin editing another user's object: allowed by design — that is what an admin control panel
  is for — but logged.
- A staff user with `must_change_password=True`: locked out of the admin until they reset.

## Security notes

- The admin is `is_staff`-gated at the `AdminSite` level, so a missing per-view check cannot
  expose it.
- `SESSION_COOKIE_SECURE` and admin-over-HTTPS-only in production (task 10).
- **No arbitrary SQL execution anywhere.** The requirement was "see the DB tables," which
  Django Admin satisfies. A raw-SQL console would be a remote code execution primitive on a
  home server, and it is deliberately not built.
- Import file size and object caps are denial-of-service protection.
- Import runs as the target owner and cannot escalate; `owner` in the payload is ignored.
- Temp passwords: generated with `secrets`, displayed once, never persisted or logged.
- Admin actions are rate-limited the same as login.
