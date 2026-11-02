/*
 * Planner profile form enhancements (N3/B2, N2/B3) — moved out of an inline <script> block in
 * profile_form.html for 10.4 (Content Security Policy): `script-src 'self'` rejects an inline
 * script tag with no nonce/hash, so this now loads as an ordinary external file instead.
 * Behaviour is unchanged from the original inline version.
 */
(function () {
  "use strict";

  // N3 / B2 — a client-side filter over the long exclusion checkbox lists. Binds to the
  // `data-checklist` container the template renders (Django's CheckboxSelectMultiple exposes
  // no usable hook of its own) and toggles each checkbox's own wrapper. No JS: the plain
  // checkbox list still works. Enter in the filter must never submit the form.
  document.querySelectorAll("[data-checklist]").forEach(function (container) {
    if (container.dataset.filterReady) { return; }
    var boxes = Array.prototype.slice.call(
      container.querySelectorAll('input[type="checkbox"]')
    );
    if (!boxes.length) { return; }
    container.dataset.filterReady = "1";
    container.classList.add("checklist-scroll");
    var filter = document.createElement("input");
    filter.type = "search";
    filter.placeholder = "Filter…";
    filter.className = "checklist-filter";
    filter.setAttribute("aria-label", "Filter this list");
    filter.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); }
    });
    filter.addEventListener("input", function () {
      var needle = filter.value.trim().toLowerCase();
      boxes.forEach(function (box) {
        var row = box.closest("div") || box.parentNode;
        row.hidden = needle !== "" && row.textContent.toLowerCase().indexOf(needle) === -1;
      });
    });
    container.parentNode.insertBefore(filter, container);
  });

  // N2 / B3 — reveal the "Add row" and per-row remove buttons for the tag-limits widget
  // when JS is available. With no JS the fixed rows still work; removing rows needs no
  // server change (blank rows serialise away).
  document.querySelectorAll("[data-tag-limits]").forEach(function (widget) {
    var add = widget.querySelector("[data-tag-limits-add]");
    var template = widget.querySelector("[data-tag-limits-template]");
    if (!add || !template) { return; }

    function wireRemove(button) {
      if (button.dataset.wired) { return; }
      button.dataset.wired = "1";
      button.hidden = false;
      button.addEventListener("click", function () {
        var row = button.closest(".tag-limit-row");
        if (row) { row.remove(); }
      });
    }

    widget.querySelectorAll("[data-tag-limits-remove]").forEach(wireRemove);
    add.hidden = false;
    add.addEventListener("click", function () {
      widget.insertBefore(template.content.cloneNode(true), template);
      widget.querySelectorAll("[data-tag-limits-remove]").forEach(wireRemove);
    });
  });
})();
