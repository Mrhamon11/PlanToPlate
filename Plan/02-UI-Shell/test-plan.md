# 02 — UI Shell · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

A UI shell resists unit testing, so the automated tests target the *contracts* other tasks will
depend on — fragment-vs-page rendering, the redirect behaviour, escaping — and the visual work
is verified manually against an explicit checklist.

## Rendering — `core/tests/test_templates.py`

| Test | Asserts |
|---|---|
| `test_base_template_renders` | A view extending `base.html` returns 200 with the nav and messages containers present. |
| `test_partials_do_not_extend_base` | Every `templates/**/_*.html` is scanned; none contains `{% extends "base.html" %}`. A partial that extends base swaps a whole page into a `div`. |
| `test_home_requires_login` | Anonymous → redirect to login. |
| `test_error_templates_render` | 403, 404, 500 templates each render standalone without a request context. |

## HTMX contract — `core/tests/test_htmx.py`

| Test | Asserts |
|---|---|
| `test_htmx_flag_set_from_header` | `request.htmx` True with `HX-Request: true`, False without. |
| `test_mixin_renders_fragment_for_htmx` | Same view + `HX-Request` returns the partial; without it, the full page. |
| `test_fragment_response_has_no_html_tag` | The fragment response body contains no `<html>` or `<body>`. |
| `test_page_works_without_htmx` | The full-page path returns complete, valid HTML — the no-JavaScript guarantee. |
| `test_htmx_auth_failure_returns_hx_redirect` | An HTMX request to a login-required view returns 200/204 with an `HX-Redirect` header, **not** a 302 whose body is a login form. |
| `test_messages_included_as_oob_on_htmx` | A fragment response carrying a message includes `hx-swap-oob`. |

## Navigation — `core/tests/test_nav.py`

| Test | Asserts |
|---|---|
| `test_admin_link_hidden_for_regular_user` | No admin URL in the rendered nav. |
| `test_admin_link_shown_for_staff` | Present for `is_staff`. |
| `test_nav_marks_current_section` | The active link carries `aria-current="page"`. |

## Security — `core/tests/test_template_security.py`

| Test | Asserts |
|---|---|
| `test_no_unjustified_safe_filter` | Grep every template for `\|safe` and `mark_safe`; the allowlist is empty at this stage, so any hit fails. Forces each future use to be a deliberate, reviewed decision. |
| `test_user_content_is_escaped` | A username containing `<script>` renders escaped in the nav. |
| `test_no_external_resource_references` | No template references an off-host `http(s)://` asset. The app must load fully with no internet access, and nothing should phone home. |
| `test_csrf_token_present_on_forms` | Every template containing `<form method="post">` also contains `{% csrf_token %}`. |

## Accessibility — `core/tests/test_a11y.py`

| Test | Asserts |
|---|---|
| `test_page_has_lang_and_title` | `<html lang>` and a non-empty `<title>`. |
| `test_viewport_meta_present` | Required for the mobile layout to apply at all. |
| `test_form_inputs_have_labels` | Every input in the rendered auth forms has an associated `<label>`. |

## Manual verification — the responsive checklist

Perform at 375px (phone), 768px (tablet), and 1440px (desktop), in both light and dark:

1. No horizontal scrolling at any width.
2. Bottom tab bar on mobile; top bar on desktop.
3. Every interactive element is at least 44×44px on touch.
4. Keyboard-only: tab through login and the nav — focus always visible, order sensible.
5. Nothing is reachable only by hover.
6. Text contrast passes 4.5:1 in both schemes (browser devtools check).
7. With JavaScript disabled, login, logout, and navigation still work.

## Definition of Done

- [ ] Every automated test above exists and passes.
- [ ] `ruff` clean; suite green.
- [ ] All seven manual checks performed at all three widths and reported.
- [ ] HTMX and Alpine are vendored — no CDN reference anywhere.
- [ ] Task 01's auth screens are restyled onto `base.html`.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
