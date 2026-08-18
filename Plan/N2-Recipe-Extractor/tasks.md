# N2 — Recipe Extractor · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

**Build N2.1 first and do not proceed until its tests pass.** Every other subtask depends on
the fetcher being safe.

- [ ] **N2.1 — SSRF-safe fetcher**
  Scheme allowlist, IP blocklist, resolve-then-connect, redirect re-validation, size and time
  caps, no credentials.
  *Files:* `extractor/services/fetch.py`
  *Done when:* every entry in the SSRF test matrix is refused.

- [ ] **N2.2 — `ExtractionJob` model**
  *Files:* `extractor/models.py`

- [ ] **N2.3 — Tier 1: JSON-LD parser**
  `schema.org/Recipe`, including graph and array forms.
  *Files:* `extractor/services/jsonld.py`

- [ ] **N2.4 — Tier 2: `recipe-scrapers`**
  With a graceful fallthrough when the site is unsupported.
  *Files:* `extractor/services/scrapers.py`

- [ ] **N2.5 — Tier 3: LLM fallback**
  Claude API with a strict JSON schema, off by default, output validated as untrusted.
  *Files:* `extractor/services/llm.py`
  *Done when:* a malformed or injected model response is rejected rather than trusted.

- [ ] **N2.6 — Ingredient line parser**
  Fractions, unicode fractions, ranges, aliases, notes, free-text fallback.
  *Files:* `extractor/services/parse.py`

- [ ] **N2.7 — Orchestration and background job**
  Tier cascade, `django-q2` task, status transitions, timeout handling.
  *Files:* `extractor/services/extract.py`, `extractor/tasks.py`

- [ ] **N2.8 — `robots.txt` and rate limiting**
  10 per user per hour; robots honoured.
  *Files:* `extractor/services/fetch.py`

- [ ] **N2.9 — API**
  Submit, poll status, fetch result.
  *Files:* `extractor/api.py`

- [ ] **N2.10 — Submit and polling UI**
  URL input, HTMX polling, clear failure messages.
  *Files:* `templates/extractor/submit.html`

- [ ] **N2.11 — Review screen**
  Pre-filled task 05 form, per-line editing, fuzzy ingredient matching shown not applied,
  unparsed lines preserved, confidence banner.
  *Files:* `templates/extractor/review.html`
  *Done when:* nothing can be saved without passing through this screen.

- [ ] **N2.12 — Audit logging**
  Every fetch attempt with URL and outcome.
  *Files:* `extractor/services/fetch.py`

- [ ] **N2.13 — Update the living document**
  *Files:* `Plan/MILESTONES.md`
