/*
 * Progressive enhancement: an element marked `data-auto-submit` submits its own form on
 * `change` instead of requiring a separate button click (10.4 — CSP replacement for an inline
 * `onchange="this.form.requestSubmit ? ... : ..."` attribute; `script-src 'self'` rejects any
 * inline handler, so this moves the same behaviour into an external, delegated listener).
 *
 * Every page using this still ships a <noscript> submit button — this is enhancement only,
 * never the only way to submit the form.
 *
 * Event delegation on document, so an element added later (an HTMX-swapped fragment) is
 * covered with no re-binding — the same pattern menus.js uses.
 */
(function () {
  "use strict";

  document.addEventListener("change", function (event) {
    var field = event.target.closest ? event.target.closest("[data-auto-submit]") : null;
    if (!field || !field.form) {
      return;
    }
    if (field.form.requestSubmit) {
      field.form.requestSubmit();
    } else {
      field.form.submit();
    }
  });
})();
