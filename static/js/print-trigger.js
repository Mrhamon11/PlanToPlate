/*
 * CSP-safe replacement for an inline `onclick="window.print()"` (10.4) on the recipe print
 * page — `script-src 'self'` rejects an inline handler. A button with no other purpose than
 * triggering the browser's print dialog has no meaningful non-JS fallback; the page itself is
 * still fully readable and printable via the browser's own print command with no script at
 * all, so this only removes the on-page shortcut.
 */
(function () {
  "use strict";

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest ? event.target.closest("[data-print-trigger]") : null;
    if (trigger) {
      window.print();
    }
  });
})();
