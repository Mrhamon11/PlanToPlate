/*
 * Dismiss disclosure menus and typeahead dropdowns on outside-click / Escape (07.18, tracked
 * app-wide as 11.25).
 *
 * Progressive enhancement only. Native <details> still toggles on its own <summary> with no
 * JavaScript, and the typeahead result lists are still populated and clickable without this
 * script — it only adds the "click away to dismiss" behaviour a pointer user expects.
 *
 *   <details class="nav-menu">  — nav profile / overflow menus, "Add to list" and "Add to
 *   book" dropdowns:
 *     - opening one closes any other that is open
 *     - a click outside an open one closes it
 *     - Escape closes the open one and returns focus to its summary
 *
 *   .component-results  — the recipe-editor.js typeahead lists on ingredient / sub-recipe /
 *   dish-recipe rows:
 *     - a click outside the row's picker, or Escape, empties the list — the same "hide
 *       results" path recipe-editor.js takes after a pick
 *
 * Event delegation on document, so rows and menus added after load are covered with no
 * re-binding.
 */
(function () {
  "use strict";

  function openMenus() {
    return Array.prototype.slice.call(document.querySelectorAll("details.nav-menu[open]"));
  }

  function forEachResults(fn) {
    Array.prototype.forEach.call(document.querySelectorAll(".component-results"), fn);
  }

  function clearTypeaheads(keep) {
    forEachResults(function (results) {
      if (results !== keep && results.innerHTML !== "") {
        results.innerHTML = "";
      }
    });
  }

  // `toggle` does not bubble — a capture-phase listener on document still sees it.
  document.addEventListener(
    "toggle",
    function (event) {
      var menu = event.target;
      if (!menu.matches || !menu.matches("details.nav-menu")) {
        return;
      }
      if (!menu.open) {
        return;
      }
      openMenus().forEach(function (other) {
        if (other !== menu) {
          other.removeAttribute("open");
        }
      });
    },
    true,
  );

  document.addEventListener("click", function (event) {
    openMenus().forEach(function (menu) {
      if (!menu.contains(event.target)) {
        menu.removeAttribute("open");
      }
    });

    var picker = event.target.closest ? event.target.closest(".component-picker") : null;
    clearTypeaheads(picker ? picker.querySelector(".component-results") : null);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") {
      return;
    }
    var menus = openMenus();
    if (menus.length) {
      var last = menus[menus.length - 1];
      last.removeAttribute("open");
      var summary = last.querySelector("summary");
      if (summary) {
        summary.focus();
      }
    }
    clearTypeaheads(null);
  });
})();
