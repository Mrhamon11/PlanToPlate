# Vendored front-end libraries

Downloaded once, checked into the repo, and never loaded from a CDN — the app runs on a home
server that may be reachable when the wider internet is not, and a CDN is a third party
watching every page load (see `Plan/02-UI-Shell/design.md`, "HTMX conventions").

To upgrade either library: re-run the matching command below, diff the result, and update the
version/date in this file.

## htmx

- **Version:** 2.0.10
- **File:** `htmx.min.js`
- **Upstream:** https://unpkg.com/htmx.org@2.0.10/dist/htmx.min.js
  (mirrors the `htmx.org` npm package, https://www.npmjs.com/package/htmx.org)
- **Fetched:** 2026-08-24
- **Re-fetch:** `curl -sL -o static/js/htmx.min.js https://unpkg.com/htmx.org@<version>/dist/htmx.min.js`

## Alpine.js

- **Version:** 3.16.3
- **File:** `alpine.min.js`
- **Upstream:** https://unpkg.com/alpinejs@3.16.3/dist/cdn.min.js
  (the `cdn.min.js` build is Alpine's own self-initializing bundle — the one their docs
  recommend for a plain `<script>` tag rather than a bundler import; mirrors the `alpinejs`
  npm package, https://www.npmjs.com/package/alpinejs)
- **Fetched:** 2026-08-24
- **Re-fetch:** `curl -sL -o static/js/alpine.min.js https://unpkg.com/alpinejs@<version>/dist/cdn.min.js`

## Loading order

`htmx.min.js` then `alpine.min.js`, both at the end of `<body>` in `templates/base.html`.
Alpine's `cdn.min.js` build auto-starts on load (it calls `Alpine.start()` itself), so no
inline bootstrap script is needed or present.
