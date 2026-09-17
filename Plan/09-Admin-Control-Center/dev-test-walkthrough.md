# 09 — Admin Control Center · Manual dev-test walkthrough

> Scratch file for the human dev-test pass. Not part of the Definition of Done — the
> automated `test-plan.md` is. This is the click-through that confirms the admin feels right in
> a browser and that the five `test-plan.md` "Manual verification" items (plus the sixth, the
> dashboard DB-size panel) are actually performed.

Runs against the DB on `fedora-headless` (the task-08 dev-test dataset is still in place). The
accounts that matter here:

| Account | Role | Use for |
|---|---|---|
| **`hamon`** | staff + superuser, owns ~41 recipes / 20 dishes / profiles / lists | the acting admin |
| **`avi`** | staff + superuser, owns 5 recipes / 4 dishes | the *second* admin (needed for last-admin tests) |
| **`alice`** | regular user, not staff | the "denied" account |

You will also **create two throwaway users** during the walk (`testuser1`, `testuser2`) and
delete one of them at the end. Nothing else is destructive — but read each step before you
click, and never run the "Reset password" or "Revoke admin" action on `hamon` or `avi` except
where a step explicitly tells you to (and tells you how to undo it).

---

## Setup

- Server: `uv run manage.py runserver 0.0.0.0:8000` on `fedora-headless`; firewall already
  opened for `tailscale0`. Admin is at
  **`http://fedora-headless.scorpion-tench.ts.net:8000/admin/`** (plain `http`, port `8000`).
- Have **two browsers** (or a normal + a private window) ready — several scenarios need one
  session as `hamon` and a second, independent session as another account.
- Passwords for the seeded accounts: whatever you set when the VM data was migrated. If you
  don't have `hamon`'s, run `uv run manage.py bootstrap_admin --force --username hamon` on the
  box to mint a fresh temp password (this is the documented recovery route; it prints the
  password once).

---

## Scenario 1 — Access control

1. **Anonymous.** Open `/admin/` in a browser with no session. **Expect:** bounced to the
   admin login page (`/admin/login/`), not a 500 or a blank page.
2. **Regular user.** Log in as `alice`. Visit `/admin/`. **Expect:** the admin login page
   again (or "You are authenticated as alice, but are not authorized…") — no changelist, no
   dashboard. Try a deep link too, e.g. `/admin/recipes/recipe/` and
   `/admin/accounts/user/create/` — each returns the login redirect or 403, never the page.
3. **Staff user.** Log in as `hamon`. Visit `/admin/`. **Expect:** the control center index
   loads with the "PlanToPlate administration" header.
4. **Staff mid-forced-change.** (Do this after Scenario 3 creates `testuser1` as staff.) Log
   in as `testuser1` — a staff account that still has `must_change_password=True` — and try to
   reach `/admin/`. **Expect:** you land on the forced-password-change screen, **not** the
   admin. An admin who hasn't completed their reset administers nothing. After you complete
   the change (Scenario 3 step 5) they *can* reach `/admin/`.
5. **Logout while forced.** As that same still-forced `testuser1`, POST to `/admin/logout/`.
   **Expect:** you end up at `/admin/` (which then bounces you) — you are not trapped on the
   change form with a 500. The working logout for a forced user is `/accounts/logout/`;
   confirm that one logs them out cleanly.

## Scenario 2 — The dashboard

On `/admin/` as `hamon`, above the stock app list there is a **Control center** module.

1. **User line:** "N users (M active, K admin)". Cross-check: K should be 2 (`hamon`, `avi`)
   right now.
2. **Database panel:** shows a real **Database file** size and a **WAL file** size, plus the
   full path to `db.sqlite3`. *(This is the sixth manual check — it only renders with real
   numbers against a file-backed DB, which is exactly this box. The test suite runs on
   `:memory:` and can't exercise it.)* Note the WAL size may legitimately read `0 B` right
   after a checkpoint.
3. **Object counts** table: one row per registered model, grouped by app, with a live row
   count. Sanity-check a couple against what you know (recipes ≈ 46, dishes ≈ 24).
4. **Recent signups:** the five newest accounts by join date.
5. **Recent admin activity:** last 10 `LogEntry` rows. Empty-ish now; it fills as you work
   through this walkthrough — come back and confirm your create-user / reset / entitlement /
   import actions all show up here.
6. **Quick actions:** "Create a user" and "Import JSON" links both resolve.

## Scenario 3 — Create a user (temp password shown once)

1. `/admin/` → **Accounts › Users › Add user** (or the "Create a user" quick link). **Expect:**
   the *custom* create page, not the stock Django add form — it has username / email / first /
   last / "is staff", and a note that the password is generated, not typed.
2. Fill in `testuser1`, tick **is staff**, submit.
3. **Expect:** a success page showing the **temporary password once**, in a `<code>` block,
   with a **Copy** button and the warning it will not be shown again. Copy it somewhere.
4. **Reload that success page.** **Expect:** the password is **gone** — the page now shows the
   plain create form again. Confirm it is nowhere else: open `/admin/accounts/user/` → click
   `testuser1` → there is no password field, no hash, nothing. Also grep the server log for
   the plaintext value — it must not appear.
5. **Log in as the new user** in a second browser with that temp password. **Expect:** forced
   straight to the password-change screen. Set a real password. **Expect:** you now have
   normal (non-admin-looking) access to the app; and because `testuser1` is staff, `/admin/`
   now works for them too.
6. Create a **second** user `testuser2`, this time **not** staff — you'll need it for the
   delete scenario. Copy its temp password too.
7. Back on the dashboard's **Recent admin activity**, confirm you see "temp password issued"
   entries for both, and an "entitlement" entry for `testuser1` (the staff one) — and that
   none of them contains the password.

## Scenario 4 — Reset password (sessions die)

1. Make sure `testuser1` is **logged in** in the second browser (on some normal app page).
2. As `hamon`, `/admin/accounts/user/` → tick `testuser1` → **Action: "Reset password (new
   temp password, end all sessions)"** → Go.
3. **Expect:** a page listing `testuser1` with a **fresh** temp password shown once, copy
   button, and text saying every existing session was ended.
4. In the second browser, click any link / reload. **Expect:** `testuser1` is logged out —
   their old session no longer authenticates. Logging back in requires the *new* temp
   password and forces another change.
5. Confirm the reset shows in **Recent admin activity** ("admin reset"), password absent.

## Scenario 5 — The disabled "set a password" form

1. As `hamon`, open `/admin/accounts/user/<testuser2 id>/password/` directly (the URL the
   stock Django admin uses for "change password").
2. **Expect:** you are redirected to the user changelist with a warning message telling you to
   use the **Reset password** action instead. There is no form here to set a chosen password —
   that path is deliberately closed (it would skip token revocation, the session kill, and the
   audit record).

## Scenario 6 — Delete a user, with preview

1. First give `testuser2` something to lose: as `hamon`, import a small file to them
   (Scenario 10) *or* just note the counts will be near-zero — either is a valid test of the
   preview.
2. As `hamon`, `/admin/accounts/user/<testuser2 id>/delete/`. **Expect:** the *custom*
   confirmation page: a bullet list of **per-model counts** of what CASCADE will destroy
   ("3 recipes, 1 dish, …" or "no owned objects"), a note that other users' *copies* survive
   with `copied_from` cleared, and a text box asking you to **type the username**.
3. Type the **wrong** text (e.g. `nope`) → submit. **Expect:** "The confirmation text did not
   match… nothing was deleted." — you're back on the confirm page, user still exists.
4. Press **Cancel**. **Expect:** back to the changelist, nothing changed.
5. Now type `testuser2` exactly → **Delete this user**. **Expect:** "Deleted user testuser2.",
   back on the changelist, the account and its owned objects are gone. The deletion shows in
   **Recent admin activity**.
6. *(If you gave `testuser2` a recipe that `hamon` had added to one of their own dishes, the
   preview shows a "protected" warning and the delete is refused with a message rather than a
   500 — worth triggering once if you have a spare minute.)*

## Scenario 7 — Admin entitlement & the last-admin guard

The guard must block the last active admin on **every** route. Right now there are two admins,
so first knock it down to one.

1. As `hamon`, `/admin/accounts/user/` → tick `avi` → **Action: "Revoke admin access
   (is_staff)"** → Go. **Expect:** "Revoked admin access from 1 account(s)." `avi` is now
   `is_staff=False`.
2. **Now try to remove your own access, four ways — each must be refused with the "only active
   admin" message:**
   - Tick `hamon` → **Revoke admin access** action → Go. **Expect:** red error, `hamon` still
     staff.
   - Open `hamon`'s change form → untick **is staff** → Save. **Expect:** form re-renders with
     the guard's validation error ("only active admin…"), nothing saved.
   - Same change form → untick **is active** → Save. **Expect:** same refusal (the guard
     covers `is_active` too).
   - `/admin/accounts/user/<hamon id>/delete/` → type `hamon` → Delete. **Expect:** refused
     with "deleting this account locks everyone out", no deletion.
3. **Grant it back:** tick `avi` → **Action: "Grant admin access (is_staff)"** → Go. `avi` is
   staff again. Confirm each grant/revoke landed in **Recent admin activity**.
4. **Change-form toggle audit:** open `testuser1`'s change form, toggle **is staff** off then
   Save, then on then Save. Each toggle should produce an entitlement entry in the activity
   log (this path audits via `save_model`, not the entitlement service).

> **Leave the box with both `hamon` and `avi` staff before you finish.**

## Scenario 8 — Every model is browsable, searchable, filterable

For **each** app section on `/admin/` (Accounts, Catalog, Recipes, Meals, Lists, Planner,
Core):

1. Open every model's changelist. **Expect:** it loads, shows a sensible `list_display`, and
   does not error. Pay attention to models added late — `RecentView` (Core), `MealPlanProfile`
   / `MealPlan` / `MealPlanEntry` (Planner).
2. Use the **search box** on models that have one (Recipes, Dishes, Ingredients, Users,
   Lists…). Search a term you know matches (e.g. `chicken` on recipes) → results filter. A
   search that hits a renamed field would 500 — it doesn't.
3. Use a couple of **list filters** (e.g. Users by `is_staff` / `must_change_password`;
   Recipes by `role`).
4. **N+1 smoke check:** open a changelist with many rows (Recipes, Ingredients) and confirm it
   returns promptly. If you want the real check, run
   `uv run pytest -k changelist_query_count_bounded`.
5. **Password never visible:** on the User changelist and change form there is no password
   column, hash, or "current password" display anywhere.

## Scenario 9 — Inlines and the recipe cycle guard

1. **Inlines render:** open a Recipe with components → its **Recipe components** inline lists
   ingredient/sub-recipe rows. Same for **Dish** (Dish components), **List** (List items),
   **Meal plan** (Meal plan entries), **Recipe book** (Recipe book entries).
2. **Cycle guard in the inline.** Pick a recipe A that is used as a sub-recipe of recipe B
   (the seed has a few — anything with a sub-recipe). Open **B** in the admin, add a component
   row whose **sub_recipe = A**, wait — you want the reverse: open **A**, add a component with
   **sub_recipe = B**, Save. **Expect:** a validation error (`assert_no_cycle` — "would create
   a cycle"), not a save and not a 500.
3. **Depth cap on the add form.** Create a fresh recipe and try to nest sub-recipes past depth
   5 — rejected with the depth message.
4. **Standalone component form.** `/admin/recipes/recipecomponent/add/` → set `recipe` and
   `sub_recipe` raw-id fields to form a cycle → Save. **Expect:** same rejection (this is the
   fourth write path).
5. **Sub-recipe unit scalability.** Add a component with a `sub_recipe` whose `yield_unit` is,
   say, `each`/`serving` and give the component a `unit` of `gram` (incompatible). **Expect:**
   a form error naming the unit, not a save. A *compatible* unit (matching dimension) saves
   fine. This is the guard that stops the flattener 500ing on dish detail / shopping-list
   generation later.

## Scenario 10 — Bulk JSON import (admin page)

1. On the box, save this as `~/import-test.json`:

   ```json
   {
     "version": 1,
     "ingredients": [
       {"name": "DT Test Flour", "default_unit": "g", "tags": ["gluten-free"]},
       {"name": "DT Test Butter", "default_unit": "g"}
     ],
     "recipes": [
       {
         "name": "DT Test Shortbread",
         "yield_quantity": "12", "yield_unit": "each", "role": "SIDE",
         "instructions": "Mix, chill, bake.",
         "components": [
           {"ingredient": "DT Test Flour", "quantity": "250", "unit": "g"},
           {"ingredient": "DT Test Butter", "quantity": "170", "unit": "g"}
         ]
       },
       {
         "name": "DT Test Cookie Plate",
         "yield_quantity": "1", "yield_unit": "each",
         "components": [
           {"sub_recipe": "DT Test Shortbread", "quantity": "6", "unit": "each"}
         ]
       }
     ],
     "dishes": [
       {"name": "DT Test Dessert", "recipes": ["DT Test Cookie Plate"], "tags": ["kid friendly"]}
     ]
   }
   ```

   Note "DT Test Cookie Plate" references "DT Test Shortbread" which is defined *before* it —
   reorder them to test **forward references** if you like; both must work.

2. `/admin/` → **Import JSON** quick link. **Owner** = `testuser1`, **Mode** = "Skip
   existing", **Dry run** ticked. Upload the file → **Import**.
3. **Expect:** a "Dry run — nothing written" panel with per-section counts (2 ingredients,
   2 recipes, 1 dish would be created). No objects actually created — check
   `/admin/recipes/recipe/?q=DT+Test`.
4. **Untick Dry run**, upload the same file again → **Import**. **Expect:** "Import complete"
   with the same counts. Now the objects exist and are owned by **`testuser1`** — verify the
   owner column on the recipe/ingredient/dish changelists.
5. **Re-import identically** (Dry run off, Skip existing). **Expect:** counts show
   2/2/1 **skipped**, 0 created — nothing duplicates.
6. Edit the JSON (change `DT Test Shortbread`'s instructions), set **Mode = "Update
   existing"**, import. **Expect:** the recipe's instructions update, still one copy.
7. **Owner cannot be forged.** Add `"owner": "hamon"` at the top level of the JSON, import
   again with **Owner = `testuser1`**. **Expect:** the key is silently ignored — everything
   stays owned by `testuser1`. This is the key import security property.
8. **Path-qualified errors.** Break the file deliberately, one at a time, and confirm each is
   rejected with a *path* and nothing is written:
   - `"unit": "cupp"` on a component → `recipes[...].components[...].unit: unknown unit 'cupp'`.
   - `"tags": ["not-a-real-tag"]` → path-qualified "unknown tag" (units/tags are never
     auto-created).
   - remove a recipe's `name` → `recipes[...].name: missing or empty required field`.
   - duplicate a recipe name in the file → "duplicate name … in recipes".
   - `"version": 2` → "unsupported version".
   - malformed JSON (delete a brace) → parse error with a position.
9. **Non-JSON upload:** upload a `.txt` / an image. **Expect:** rejected at the form, not a
   500.
10. Confirm an "import" entry (with counts, no object names) appears in **Recent admin
    activity** for the real imports — and **not** for the dry runs.

## Scenario 11 — Bulk JSON import (management command)

On the box:

```bash
uv run manage.py import_json ~/import-test.json --owner testuser1 --dry-run
uv run manage.py import_json ~/import-test.json --owner testuser1            # skip-existing default
uv run manage.py import_json ~/import-test.json --owner testuser1 --update-existing
uv run manage.py import_json ~/import-test.json --owner nosuchuser           # → CommandError
uv run manage.py import_json ~/broken.json --owner testuser1                 # → "Import rejected:" + paths, exit non-zero
```

**Expect:** identical behaviour to the admin page (same validation, same skip/update
semantics, atomic). `--owner` is **required** here (a shell run has no request user).

## Scenario 12 — Things that must NOT exist

1. **No raw-SQL endpoint.** There is no "run SQL" / "query" page anywhere in the admin. Poke
   at guessed URLs (`/admin/sql/`, `/admin/shell/`) → 404.
2. **`authtoken` is gone from the admin.** `/admin/` has no "Tokens" / "Auth Token" section.
   `/admin/authtoken/tokenproxy/add/` → 404 / `NoReverseMatch`. Minting a token by hand with
   no audit trail is deliberately not available.
3. **Custom actions are POST-only and CSRF-protected** — you can't trigger "Reset password" or
   "Delete user" by pasting a GET URL; the forms carry `{% csrf_token %}`.

## Scenario 13 — Cleanup

1. Delete `testuser1` via the guarded delete flow (Scenario 6) — type the username, confirm.
   That also removes the imported `DT Test *` objects (they're owned by `testuser1`, CASCADE).
   If you imported anything to `testuser2` earlier and it's already deleted, nothing to do.
2. Double-check no `DT Test` recipes/ingredients/dishes remain
   (`/admin/recipes/recipe/?q=DT+Test`).
3. Confirm **`hamon` and `avi` are both still staff + active**.
4. `rm ~/import-test.json ~/broken.json` on the box.

---

## What matters most

- A staff account mid-forced-password-change **cannot reach the admin** (Scenario 1.4).
- A temp password is shown **exactly once**, is in **no** column and **no** log (Scenario 3).
- Resetting a password **kills the existing session** (Scenario 4).
- The **last admin cannot be locked out** by any of the four routes (Scenario 7).
- Import is **atomic**, its errors are **path-qualified**, and the file **cannot set `owner`**
  (Scenario 10).
- **No arbitrary-SQL / token-minting back door** exists (Scenario 12).
