# 08 — Meal Planner · Manual dev-test walkthrough

> Scratch file for the human dev-test pass. **Delete before merging `task/08-meal-planner`.**
> Not part of the Definition of Done — the automated `test-plan.md` is. This is the
> click-through that confirms the feature feels right in a browser.

Runs against the dev-test dataset seeded on `fedora-headless` (2026-09-06). If that data is
gone, re-seed from the session scratchpad `seed_devtest.py` or rebuild equivalent data:
~20 dishes for `hamon` spanning all roles, 6 planner profiles, ratings/favourites, a few
"made" dishes, two dishes with a buried allergen, and 4 dishes for `avi` (2 shared → hamon,
2 public).

---

## Setup

- Server: `uv run manage.py runserver 0.0.0.0:8000` on `fedora-headless`; firewall already
  opened for `tailscale0`. Open **`http://fedora-headless.scorpion-tench.ts.net:8000/`**
  (plain `http`, port `8000`).
- **Log in as `hamon`.** All the dishes, ratings and profiles are on that account.
- The planner has no "seed" field in the UI — each **Generate** press uses fresh randomness.
  The determinism guarantee you can *see* is: locked slots never change, and **Save** stores
  exactly the week shown in the preview.

### The seeded profiles and what each one is for

| Profile | Settings | Exercises |
|---|---|---|
| **Weeknight Dinners** (default) | 7 days, dinner, Balanced, *my dishes*, no-repeat 14 | the core flow, no-repeat |
| Quick Weeknights | 5 days, dinner, Mix, *my dishes*, max 45 min | gear 8 (time budget) |
| One-Pot Week | 7 days, dinner, One-pot, *my dishes* | template = one-pot |
| Full Day Plan | 3 days, breakfast + lunch + dinner, Mix, *+ shared* | multi-slot, shared scope |
| Family Favourites | 6 days, dinner, Balanced, *+ public*, min rating 4, favourites bias 3× | gear 7, public scope |
| Nut-Free Kitchen | 7 days, dinner, Mix, *my dishes*, excludes Peanut Butter / Walnuts / Almonds | gear 5 (allergy) |

### Dishes worth knowing for the assertions

- **Chicken-tagged** (for tag limits): Roast Chicken Dinner, Lemon Chicken Quinoa Bowl,
  Chicken & Rice Skillet, Pesto Chicken Pasta.
- **Marked "made" recently** (excluded by no-repeat 14): Roast Chicken Dinner (today),
  Crispy Tofu Bowl (1 day), Chicken & Rice Skillet (3 days). Steakhouse Night was made 20
  days ago — still eligible.
- **Buried allergen**: *Thai Peanut Noodle Bowl* (peanut butter only inside its Peanut Sauce
  sub-recipe), *Pesto Chicken Pasta* (walnuts only inside its Pesto sub-recipe).
- **From `avi`**: shared → Sunday Pot Roast, Turkey Chili & Cornbread; public → Pot Roast &
  Biscuits, Cornbread Chili Bowl.

---

## Scenario 1 — Planner is reachable

1. Click **Planner** in the top nav.
2. **Expect:** the "Meal planner" page with a **Generate a week** button, a "Your plans"
   section (empty), and the six profiles listed.

## Scenario 2 — Generate a week

1. **Generate a week** → profile **Weeknight Dinners**, pick a start date, leave Days blank.
2. **Generate.**
3. **Expect:**
   - A preview grid, **Day 1 … Day 7**, each with one **Dinner** card naming a dish + date.
   - "7 slots filled, 0 still open" (or a note that fewer filled, with a reason on each empty
     card).
   - **No dish name appears twice.**
   - Roast Chicken Dinner, Crispy Tofu Bowl and Chicken & Rice Skillet do **not** appear —
     they were cooked within the last 14 days.
   - Text saying nothing is saved yet.
4. Press **Generate** again → a different week, still no repeats.

## Scenario 3 — Save

1. Name it `Test week`, press **Save this plan**.
2. **Expect:** "Plan saved.", you land on the plan page showing the **same** week as the
   preview, and it appears under "Your plans".
3. Press **Rename** → change the name → **Save name**. Heading and the index card update.
   Clearing the name is allowed — the plan then shows as "Untitled plan". A shared viewer
   (`avi`) never sees the Rename control.

## Scenario 4 — Lock and re-roll

1. On the saved plan, **Lock** Day 1 and Day 2.
2. Press **Re-roll unlocked slots**.
3. **Expect:** Days 1–2 unchanged; Days 3–7 change; still no dish twice.
4. Press it again — locked days never move.
5. Press **Re-roll** on a single card → only that card changes.

## Scenario 5 — Swap and clear

1. On an unlocked card, use **Swap / clear…** → pick a specific dish. Card updates in place.
2. Use it again → **— clear this slot —**. Card shows **Empty** with a re-roll hint.
3. Re-roll that card → fills with something not already used that week.

## Scenario 6 — The rules bite

Edit **Weeknight Dinners** (Planner → Manage profiles), save, then **Generate a week** fresh
each time.

| Change | Expect |
|---|---|
| Limits → Tag limits: `{"chicken": 1}` | Exactly **one** chicken dish across the 7 days (4 are available). |
| Tag limits: `{"chicken": 0}` | **No** chicken dish. |
| Limits → Excluded tags: tick `italian` | Spaghetti Marinara Dinner / Pesto Chicken Pasta etc. never appear. |
| Limits → Excluded ingredients: `Peanut Butter` | Thai Peanut Noodle Bowl never appears — allergen is only in its sub-recipe. |
| Quality → Minimum rating 4 | Only dishes you rated 4–5 appear (Pork Tenderloin Plate, Chickpea Coconut Curry, Polenta & Meatballs drop out — rated 3). |
| Quality → Favourites bias 5, and generate ~5 times | Roast Chicken Dinner / Lemon Chicken Quinoa Bowl / Crispy Tofu Bowl / Chicken & Rice Skillet / Shrimp Fried Rice show up noticeably more often (they're favourited). |
| Quality → Max total minutes 30 | Only quick dishes; anything with a long recipe (Beef Chili Bowl at 45 min cook, etc.) drops. |

While editing the profile: the **Excluded tags / ingredients** groups now render as checkbox
lists with a **Filter…** box above each — typing narrows the visible checkboxes, and pressing
Enter in that box filters rather than submitting the form. **Tag limits** starts at 3 rows,
each with an **×** button to drop it, and **Add row** for more.

Reset the profile (clear tag limits, min rating, max minutes) when done.

Or just switch profiles: **Nut-Free Kitchen** should never surface *Thai Peanut Noodle Bowl*,
*Pesto Chicken Pasta*, *Turkey Meatball Dinner* or *Pork Tenderloin Plate* (the last two use
Almond Green Beans). **One-Pot Week** should only pick one-pot dishes. **Full Day Plan** gives
3 days × breakfast/lunch/dinner and can use `avi`'s shared dishes.

## Scenario 7 — Change plan length

1. On a saved 7-day plan, **Length → 5 days → Change**.
2. **Expect:** a confirm dialog: N slots beyond day 5 will be removed, cannot be undone.
   **Cancel** → nothing changes.
3. Repeat → **Remove them** → plan is now 5 days.
4. **Length → 7 days → Change** → no warning; days 6–7 come back **empty**, re-rollable.

## Scenario 8 — Shopping list

1. On a saved plan with filled dinners, press **Shopping list**.
2. **Expect:** aggregated ingredient lines (an ingredient used by three dinners shows once,
   summed).
3. Tick **Leave out pantry staples** → list re-loads shorter, "N staples left out".
4. Press **Generate shopping list** → "Shopping list updated.", lands on the list with those
   items.
5. Add a manual item of your own, check it off. Back on the plan → **Shopping list** →
   **Regenerate shopping list**.
6. **Expect:** quantities are the **same, not doubled**; your manual item and its checked
   state **survive**. If regenerating would wipe items you'd already checked, the preview
   warns first.

## Scenario 9 — Source scope

**Note (2026-09-07):** the default **Weeknight Dinners** profile is *Balanced*, and strict
Balanced only ever selects a dish covering protein + carb + vegetable (or composes one from
recipes) — it has **no** fallback to a partial or one-pot dish. So under Balanced only
P/C/V-complete shared/public dishes can surface (e.g. Sunday Pot Roast); the partial /
one-pot public dishes (Pot Roast & Biscuits, Cornbread Chili Bowl) can only appear once the
profile's template is switched to **Mix** or **One-pot**. This is working as designed — the
pool *does* contain those dishes at the right scope, the Balanced template just won't pick
them.

1. Set **Weeknight Dinners** → Source = **Only my dishes**, generate. `avi`'s dishes
   (Sunday Pot Roast etc.) never appear.
2. Source = **My dishes and dishes shared with me**, generate several times. Sunday Pot Roast
   (a P/C/V-complete dish) can now appear.
3. Source = **… and public dishes**. Switch the template to **Mix** and generate several
   times → the one-pot / partial public dishes (Pot Roast & Biscuits, Cornbread Chili Bowl)
   can also appear.

## Scenario 10 — Empty-handed

1. **Weeknight Dinners** → Source = *my dishes*, Excluded tags = tick every tag you can →
   Generate.
2. **Expect:** a "Nothing to plan yet" panel explaining why, with links forward — not a blank
   grid or a wall of empty cards.
3. (Optional) Log in as a fresh account with no dishes → Planner → same guidance with a
   **Create a dish** button.

## Scenario 11 — Shared plan is read-only (needs the second account)

1. As `hamon`, open a saved plan and use its **Share** control to share it with `avi`.
2. As `avi`, open it → can read the week, but **no** Lock / Re-roll / Swap / Regenerate /
   Length / Shopping-list controls, and `hamon`'s profile name and rules are not shown.

## Scenario 12 — Phone

1. Open a saved plan on a phone / narrow window.
2. **Expect:** days stack vertically, every card's controls are tappable, no horizontal
   scroll.

---

## What matters most

- A rule you set is **never silently ignored** — you get a partial week with a reason.
- Regenerating the shopping list **never doubles** quantities, and never loses manual items.
- The planner **never suggests a dish you can't see** (Scenario 9).
