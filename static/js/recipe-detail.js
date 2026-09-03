/*
 * Recipe detail page (Plan/05-Recipes/design.md, "UI": "Recipe detail").
 *
 * Two small enhancements htmx can't express on its own:
 *  - the sub-recipe expander is a toggle: htmx loads the inlined ingredients once
 *    (hx-trigger="click once"), this script shows/hides them and flips the +/− glyph;
 *  - the "Cook for" scale <select> is reset to ×1 on a fresh page load, because a browser
 *    restoring the previously-picked option would leave the label disagreeing with the
 *    server-rendered (unscaled) quantities.
 *
 * Event delegation on document, so htmx-swapped content needs no re-binding.
 */
(function () {
  "use strict";

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-subrecipe-toggle]");
    if (!toggle) {
      return;
    }
    var row = toggle.closest(".component-row");
    var panel = row && row.querySelector(".subrecipe-expansion");
    if (!panel) {
      return;
    }
    // htmx (hx-trigger="click once") fills the panel on the first click; from then on this is
    // the only thing that shows or hides it.
    var willOpen = panel.hidden;
    panel.hidden = !willOpen;
    toggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
    toggle.textContent = willOpen ? "−" : "+";
  });

  function resetScaleControl() {
    var select = document.getElementById("scale-factor");
    if (select) {
      select.value = "1";
    }
  }

  window.addEventListener("pageshow", function (event) {
    // A bfcache restore (event.persisted) brings the matching scaled DOM back with it, so leave
    // it alone; only a genuine load, where the quantities are freshly unscaled, needs the reset.
    if (!event.persisted) {
      resetScaleControl();
    }
  });
})();
