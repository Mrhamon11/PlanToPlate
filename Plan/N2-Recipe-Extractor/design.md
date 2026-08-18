# N2 — Recipe Extractor · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)
>
> *Nice-to-have, and the most security-sensitive feature in the backlog. The design is lighter
> than the MVP tasks except for the SSRF section, which is not negotiable.*

## Goal

Paste a URL, get a draft Recipe, review and edit it, save it. Never save without human review.

**Depends on:** 05, N1, and 10's security posture.

## Extraction strategy — cheapest and most reliable first

`MILESTONES.md` C11. The requirement suggested deploying an AI agent to crawl the page. That is
the *last* resort, not the first: most recipe sites already publish their recipe as structured
data, and parsing it is free, instant, and exact.

**Tier 1 — `schema.org/Recipe` JSON-LD.** Present on the large majority of recipe sites because
it is what earns them a rich result in search. Gives name, ingredients, instructions, yield,
times, and image as clean fields. No AI, no cost, no hallucination.

**Tier 2 — `recipe-scrapers`.** A maintained library with per-site parsers covering hundreds of
popular sites. Handles the ones with broken or absent JSON-LD.

**Tier 3 — LLM fallback.** Only when 1 and 2 fail. Send the *extracted text* (not raw HTML) to
the Claude API with a strict JSON output schema, and mark the result low-confidence. Off by
default; requires an API key in the environment.

Each tier records which one produced the result so the review screen can set expectations.

## SSRF protection — the non-negotiable part

`MILESTONES.md` §6.4. **This feature takes a URL from a user and fetches it from a machine
inside a home network.** That is a textbook server-side request forgery primitive: without
guards, a user can make the server request `http://192.168.1.1/`, a Tailscale peer, a cloud
metadata endpoint, or `file:///etc/passwd`, and read the response back through the review
screen.

`extractor/services/fetch.py`:

1. **Scheme allowlist:** `http` and `https` only. No `file`, `ftp`, `gopher`, `data`.
2. **Resolve the hostname first**, then check every resolved IP against a blocklist:
   loopback, private ranges (RFC1918), link-local (169.254.0.0/16 — this is the cloud metadata
   endpoint), CGNAT (100.64.0.0/10 — this is Tailscale), multicast, reserved, and IPv6
   equivalents including IPv4-mapped forms.
3. **Connect to the validated IP**, passing the hostname via SNI and `Host`. This closes the
   DNS-rebinding window between check and connect — validating a hostname and then letting the
   HTTP client re-resolve it is the classic bypass.
4. **Re-validate on every redirect.** Cap at 3 hops. A permitted URL redirecting to
   `169.254.169.254` is the most common real-world SSRF chain.
5. Caps: 5 second connect, 15 second total, 2 MB response body, `text/html` only.
6. No credentials, no cookies, no proxy inheritance.
7. Rate limit: 10 extractions per user per hour.

**Fail closed.** Any uncertainty — unresolvable host, mixed public/private resolution — is a
refusal.

## Background processing

Fetching is slow and unpredictable, so it runs through `django-q2` (`MILESTONES.md` §2 — chosen
over Celery because it needs no Redis at this scale).

```python
class ExtractionJob(models.Model):
    owner, url, status, tier_used, confidence
    raw_result = JSONField(null=True)
    error = TextField(blank=True)
    created_at, completed_at
    recipe = FK(Recipe, null=True)      # set once the user saves
```

The UI polls with `hx-trigger="every 2s"` until the job resolves.

## Review screen — mandatory

The requirement is explicit and correct: users review and edit before saving. Nothing is ever
written straight to the recipe database.

The screen is task 05's recipe form, pre-filled, with:
- Ingredient lines parsed into quantity / unit / ingredient, each editable.
- Unmatched ingredient names offered as quick-add (task 04) or fuzzy-matched to existing ones
  with the match shown, never silently applied.
- Unparseable lines kept as free text with a warning rather than dropped — losing an ingredient
  silently is worse than showing a messy one.
- `source_url` populated (the field already exists from task 05).
- A confidence banner when tier 3 produced the result.

## Ingredient line parsing

`extractor/services/parse.py`: `"2 1/2 cups all-purpose flour, sifted"` →
`(Decimal("2.5"), cup, "all-purpose flour", "sifted")`.

Handles unicode fractions (½), ranges ("2–3 cloves", take the midpoint and flag it), unit
aliases and plurals, parenthetical notes, and leading or trailing preparation text. Anything
that does not parse falls through to free text with the original preserved.

## Legal and etiquette

- Honour `robots.txt`.
- Identify with a real User-Agent naming the app.
- Personal use, one page at a time, rate-limited. **No crawling, no bulk import of a site.**
- Store `source_url` and attribute it on the recipe.
- The runbook should note that recipe *text* is generally not copyrightable but the surrounding
  prose is — so extraction stores ingredients and steps, not the author's story.

## Edge cases

- Paywalled or JS-rendered pages: fail with a clear message. **Headless browser rendering is
  out of scope** — it is a large dependency and a much bigger attack surface.
- Multiple recipes on one page: extract the first, tell the user, offer a picker if JSON-LD
  provides several.
- Non-English pages: tiers 1 and 2 often still work; units may not parse, which falls through
  to free text.
- A URL that is already extracted: offer the existing recipe rather than duplicating.
- A job that never completes: timeout marks it failed with a reason.

## Security notes

Beyond SSRF:

- LLM output is **untrusted input**: validate it against the schema, never `eval` it, never let
  it set `owner`, IDs, or visibility. Treat prompt-injected content in a fetched page as
  hostile — the page author controls the text the model sees.
- Fetched HTML is never rendered. Text is extracted and escaped.
- The API key lives in the environment, never in the database or client.
- Extraction jobs are per-user and private.
- The 2 MB and time caps are denial-of-service protection.
- Every fetch attempt is logged with the URL and the outcome, so a misuse pattern is visible.
