# 12 — Home Dashboard · Manual dev-test walkthrough

> Scratch file for the human dev-test pass. **Delete before merging `task/12-home-dashboard`.**
> Not part of the Definition of Done — the automated `test-plan.md` is. This is the
> click-through that confirms the dashboard feels right in a browser.

Runs against the **task-08 dev-test dataset** already seeded on `fedora-headless`
(2026-09-06): `hamon` has ~41 recipes, 20 dishes, 5 dish favourites, ratings, a default
Shopping List with 3 manual items, and 6 planner profiles; `avi` owns 4 dishes — **2 shared
to `hamon`** (Sunday Pot Roast, Turkey Chili & Cornbread) and **2 public** (Pot Roast &
Biscuits, Cornbread Chili Bowl). If that data is gone, re-seed from the session scratchpad
`seed_devtest.py`.

This task adds no seed data of its own. Two things you create by hand during the run:

1. **A saved meal plan for `hamon` that covers today** (Scenario 3) — the "This week" panel
   has nothing to show until one exists.
2. **Recently-viewed history** — the table starts empty; you build it up by opening detail
   pages in Scenario 5.

---

## Setup

- Server: `uv run manage.py runserver 0.0.0.0:8000` on `fedora-headless`; firewall already
  opened for `tailscale0`. Open **`http://fedora-headless.scorpion-tench.ts.net:8000/`**
  (plain `http`, port `8000`).
- **Log in as `hamon`** for Scenarios 1–9 and 12–14. Scenarios 7–8 and 14 also need `avi`.
- After login you land on `/` — the dashboard *is* the home page.
- The "What should I make?" panel re-rolls with fresh randomness on every press; there is no
  seed field. What you can verify is *which* dishes are eligible and that the re-roll swaps
  only that one panel.

### The panels, in render order

| Panel | Shows | When it hides |
|---|---|---|
| **This week** | `hamon`'s active plan covering today — today first, next 2 days, each slot's dish linked | no owned plan covers today |
| **Shopping** | `hamon`'s **default** list only — `checked / total`, first 8 unchecked grouped by aisle | no default shopping list |
| **Recently viewed** | last ~8 recipes / dishes / books opened, newest first, tagged by kind | nothing viewed yet |
| **Favourites** | favourited recipes + dishes, A–Z, tagged by kind, capped 8 | no visible favourites |
| **Shared with you** | dishes/recipes/books **explicitly shared** with `hamon`, "from `<owner>`" | none |
| **Public from others** | objects visible to `hamon` **only because they're public** | none |
| **What should I make?** | one random visible dish with ≥1 component, re-rollable | `hamon` can see no such dish |
| **Browse** | the five section links + a live count each | **never** — this is the floor |

---

## Scenario 1 — First load reads as an answer, not a menu

1. Log in as `hamon`.
2. **Expect:**
   - Heading **"Welcome back, hamon"** and the line *"What you're cooking, and what you need
     to buy."*
   - A grid of panels (see table above) ending with a **Browse** panel.
   - **No "Coming soon."** text anywhere, and **no** five-card section grid from task 02.
   - Every panel that renders has real content in it — no empty boxes, no "Loading…", no
     spinner.

## Scenario 2 — Browse panel is the floor

1. Scroll to **Browse**.
2. **Expect:** exactly five links — **Recipes, Dishes, Books, Lists, Meal plans** — each with
   a number beside it. (Books is likely `0` unless you have made one.)
3. Open each section from the top nav and confirm the count on Browse matches what you
   actually see listed there (the count is visibility-scoped, not a raw table count).
4. Click each Browse link → lands on `/recipes/`, `/dishes/`, `/books/`, `/lists/`,
   `/planner/` respectively.

## Scenario 3 — This week

1. First, before creating a plan: if no saved plan of `hamon`'s covers today, **the "This
   week" panel is absent** (not an empty "No plan yet" card — see the note at the end).
2. Go to **Planner → Generate a week**, profile **Weeknight Dinners**, **start date = today**,
   Generate → **Save this plan**, name it `Dashboard test`.
3. Back to **Home**. **Expect** the **This week** panel:
   - Panel title "This week" with the plan name **`Dashboard test`** as a link → the plan
     page.
   - Up to **3** days listed, **today first**, today's row visually marked and carrying a
     **"Today"** badge.
   - Each day's dinner slot names its dish as a **link** → that dish's detail page.
4. Edit the saved plan so it **starts 2 days ago** (Planner UI, or leave it — generate a
   second plan with start date 2 days ago and save it). Reload Home.
   - **Expect:** the panel still shows, and it **starts at today** — not at day 1 of the
     plan. The two days already in the past are not shown.
5. Change a plan to one that **ended yesterday** (start 7+ days ago). Reload Home.
   - **Expect:** the **This week** panel is **gone** — a plan that ended yesterday is not
     "this week", and the dashboard does not fall back to showing the most recent plan.

## Scenario 4 — Shopping

1. With `hamon`'s default Shopping List holding its 3 seeded manual items and nothing checked:
2. **Expect** the **Shopping** panel:
   - Title "Shopping", the list name as a link → the list page.
   - **"0 of 3 items checked"**.
   - The 3 items, grouped under their aisle headings exactly as the list page groups them.
3. On the list page, tick one item. Reload Home → **"1 of 3 items checked"**, that item no
   longer in the preview.
4. From the saved plan (Scenario 3) press **Shopping list → Generate shopping list** so the
   default list now has many items. Reload Home.
   - **Expect:** progress count reflects the new total, only the **first 8 unchecked** items
     are previewed, and a **"+ N more to buy"** line below.
5. Delete every item from the list (or check them all). Reload Home.
   - Panel still renders (the list exists), showing **"Nothing left to buy."**

## Scenario 5 — Recently viewed

1. Fresh state: no detail pages opened this session's history → **panel absent**.
2. Open, in this order: a **recipe** detail page, then a **dish** detail page, then (if you
   have one) a **book**. Return Home.
   - **Expect** a **Recently viewed** panel: those objects, **newest first** (book/dish on
     top), each with a small **Recipe / Dish / Book** kind tag, each a link.
3. Open the **first** recipe again → return Home.
   - **Expect:** it moves to the **top**, and there is still only **one** row for it — the
     timestamp was bumped, not a second entry appended.
4. On a recipe detail page, use the **scale** control or expand a **sub-recipe** (both are
   HTMX fragment loads). Return Home.
   - **Expect:** order **unchanged** — a fragment refresh is not a fresh view.
5. Open a **recipe list** page and a recipe **print** page. Return Home.
   - **Expect:** neither is recorded — scrolling past a card, or printing, is not viewing.
6. Open more than 8 distinct detail pages. Home shows only the **most recent ~8**.

## Scenario 6 — Favourites

1. **Expect** a **Favourites** panel listing `hamon`'s favourited dishes (5 from the seed)
   plus any favourited recipes, **A–Z**, each kind-tagged, **capped at 8**.
2. On one favourited dish's detail page, click the favourite toggle **off**. Reload Home.
   - **Expect:** that dish is **gone** from the panel.
3. Toggle it back on → it returns on the next load.

## Scenario 7 — Shared with you (needs `avi`)

1. As `hamon`, **Expect** a **Shared with you** panel listing **Sunday Pot Roast** and
   **Turkey Chili & Cornbread**, each labelled **"from avi"**, kind-tagged **Dish**.
2. **Not** in this panel: Pot Roast & Biscuits, Cornbread Chili Bowl (those are public, not
   shared — Scenario 8).
3. The panel shows **only** the owner's username. There is nowhere on the card that names
   anyone *else* a dish is shared with (D35 — the share audience is owner-only).

## Scenario 8 — Public from others

1. As `hamon`, **Expect** a **Public from others** panel listing **Pot Roast & Biscuits** and
   **Cornbread Chili Bowl**, each **"from avi"**, kind **Dish**.
2. **Sunday Pot Roast is not here** — it is an explicit share, so it appears in Scenario 7's
   panel and this one, **never both**.
3. From Pot Roast & Biscuits' detail page, **Copy** it to your own. Reload Home.
   - **Expect:** your copy (now owned by `hamon`) is in **neither** "Public from others" nor
     "Shared with you". Delete the copy afterwards to keep the dataset clean.

## Scenario 9 — What should I make?

1. **Expect** a **What should I make?** panel: one dish name as a link, and a **"Show me
   another"** button.
2. Press **"Show me another"** (JavaScript on) several times.
   - **Expect:** only that panel's dish swaps. The rest of the page — This week, Shopping,
     everything — does **not** reload or flicker. *(This is the exact task-06 item-10 bug:
     the re-roll must target the panel, not the button.)*
3. The suggested dish is always one `hamon` can see and one with at least one component. The
   seed's empty **"Empty"** dish and any component-less junk never appear. `avi`'s shared /
   public dishes **can** appear — they are visible to `hamon`, which is correct.

## Scenario 10 — Brand-new user

1. Register a fresh account (or use one with no data), log in.
2. **Expect:**
   - "Welcome back, `<name>`".
   - If the account can see nothing at all: the line **"Nothing here yet — add your first
     recipe to get started."**
   - The **Browse** panel, with its counts (mostly `0`).
   - **No other panels** — no empty This week / Shopping / Recently viewed boxes.
3. The page must read as **deliberate**, not broken. Note whether the "get started" line
   appears or whether system-visible objects push the section counts above zero (in which
   case you get the normal subtitle and just the Browse panel).

## Scenario 11 — Read-only API

1. Logged in as `hamon`, open **`/api/dashboard/`** (DRF browsable API).
2. **Expect** JSON with keys `this_week`, `shopping`, `recently_viewed`, `favourites`,
   `shared_with_you`, `public_from_others`, `suggestion`, `sections`, `show_get_started` —
   and the contents match what the home page just showed you (same dishes, same counts).
3. The browsable API offers **no POST/PUT/PATCH/DELETE form**. A `curl -X POST` against it
   → **405**.
4. Hit `/api/dashboard/` with no session → **403 / 401**, not data.

## Scenario 12 — No JavaScript

1. Disable JavaScript in the browser, reload `/`.
2. **Expect:** every panel is **fully rendered** on that first response — This week, Shopping,
   Recently viewed, Favourites, both "from others" panels, the suggestion, Browse. Nothing is
   blank, nothing says "enable JavaScript".
3. **"Show me another"** now does a full-page reload of `/` and comes back with a fresh
   suggestion. All other panels re-render unchanged.

## Scenario 13 — Phone / narrow window

1. Open `/` on a phone or a narrow window.
2. **Expect:** panels stack to a **single column** on a phone, 2 columns mid-width, 3 on a
   wide screen. **No horizontal scroll.** Every link and the re-roll button are tappable.

## Scenario 14 — Revoked access is re-filtered at render (the security case)

1. As `hamon`, open **Sunday Pot Roast** (shared by `avi`). It now appears in **Recently
   viewed**. Favourite it too, so it also appears in **Favourites**.
2. As `avi`, open Sunday Pot Roast → **Share** → remove `hamon` from the audience.
3. As `hamon`, reload `/`.
   - **Expect:** Sunday Pot Roast is **gone** from Recently viewed, from Favourites, and from
     "Shared with you" — on every panel. The dashboard never renders it from the stored
     recently-viewed / favourite row once access is gone.
4. As `avi`, re-share it with `hamon` to restore the dataset.

---

## What matters most

- **No panel ever shows an object `hamon` cannot currently see** — a recently-viewed row, a
  favourite, or a share that has since been revoked all vanish on the next load (Scenario 14).
- **Shared vs. Public is a clean split** — an object owned by someone else is in exactly one
  of those two panels, never both (Scenarios 7–8).
- **The page is never blank** — Browse is always there, even for a brand-new user (Scenarios
  2, 10).
- **Re-roll swaps only the suggestion panel** (Scenario 9).
- **The whole dashboard works with JavaScript disabled** (Scenario 12).
- **The share audience never leaks** — panels show an owner's username and nothing else about
  who a thing is shared with (Scenarios 7–8).

## Things to flag if they bite

- `design.md`'s panel table gives **This week** and **Shopping** a *visible* empty state
  ("No plan yet" / "Nothing on the list" with a forward link). The build instead **hides**
  both panels when empty, consistent with "panels with nothing to say hide themselves." If
  the hidden-not-shown behaviour feels wrong for these two flagship panels, raise it — it is
  a design-vs-build discrepancy, not a bug in the code as written.
- Whether a brand-new user actually sees the "get started" line depends on there being **zero**
  visible objects in every section; seeded system data can suppress it. Note what you see.
- A brand-new user also sees **every `PUBLIC` object any other user owns** — `visible_to` returns
  `PUBLIC` rows to every account, so the **Public from others** panel renders for them and the
  section counts go above zero whenever public content exists. `design.md`'s line "a brand-new
  user sees the section cards, their counts, and nothing else" assumes no public content exists;
  it is not a bug. Seen during the 2026-09-07 dev test with `alice` (five of `avi`'s recipes
  were stranded `PUBLIC` after their parent dishes were reverted from public — see
  `Plan/11-TaskBugFixes/tasks.md` 11.11 / D31).
