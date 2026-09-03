/*
 * Recipe form editor (Plan/05-Recipes/design.md, "UI": "Recipe form").
 *
 * Progressive enhancement over server-rendered rows: htmx does the typeahead fetches and the
 * "add row" swaps; this script only wires the interactions htmx cannot express on its own —
 * turning a typeahead result (or a quick-added ingredient) into the row's chosen reference,
 * removing a row, and reordering rows so their submit order becomes their saved position.
 *
 * Event delegation on document/body, so rows added after load are handled with no re-binding.
 */
(function () {
  "use strict";

  function closestRow(el) {
    return el.closest("[data-component-row]");
  }

  function chooseComponent(row, choice) {
    var kindInput = row.querySelector('[data-role="kind"]');
    var refInput = row.querySelector('[data-role="ref"]');
    var label = row.querySelector('[data-role="label"]');
    var search = row.querySelector('[data-role="search"]');
    var results = row.querySelector('[data-role="results"]');

    if (choice.kind) {
      kindInput.value = choice.kind;
    }
    refInput.value = choice.ref || "";
    // Always visible: empty text falls back to the placeholder caption (CSS :empty::before),
    // so the picker column keeps the same height as the Qty / Unit / Note columns and their
    // inputs stay aligned.
    label.textContent = choice.label || "";
    if (search) {
      search.value = "";
    }
    if (results) {
      results.innerHTML = "";
    }

    if (choice.unitId) {
      var unitSelect = row.querySelector('select[name="component_unit"]');
      if (unitSelect && !unitSelect.value) {
        unitSelect.value = choice.unitId;
      }
    }
  }

  document.addEventListener("click", function (event) {
    var chooseBtn = event.target.closest("[data-choose]");
    if (chooseBtn) {
      var row = closestRow(chooseBtn);
      if (row) {
        chooseComponent(row, {
          kind: chooseBtn.dataset.kind,
          ref: chooseBtn.dataset.ref,
          label: chooseBtn.dataset.label,
          unitId: chooseBtn.dataset.unitId,
        });
      }
      return;
    }

    var removeBtn = event.target.closest("[data-remove-row]");
    if (removeBtn) {
      var rowToRemove = closestRow(removeBtn);
      var list = rowToRemove && rowToRemove.parentElement;
      if (list && list.querySelectorAll("[data-component-row]").length > 1) {
        rowToRemove.remove();
      } else if (rowToRemove) {
        // Keep the last row but clear it rather than leaving an empty editor.
        chooseComponent(rowToRemove, { ref: "", label: "" });
      }
      return;
    }

    var moveBtn = event.target.closest("[data-move-row]");
    if (moveBtn) {
      var movingRow = closestRow(moveBtn);
      if (!movingRow) {
        return;
      }
      if (moveBtn.dataset.moveRow === "up" && movingRow.previousElementSibling) {
        movingRow.parentElement.insertBefore(movingRow, movingRow.previousElementSibling);
      } else if (moveBtn.dataset.moveRow === "down" && movingRow.nextElementSibling) {
        movingRow.parentElement.insertBefore(movingRow.nextElementSibling, movingRow);
      }
    }
  });

  // task 04's quick-add returns _ingredient_row.html into the row's results container; adopt
  // the just-created ingredient as this row's choice.
  document.body.addEventListener("htmx:afterSwap", function (event) {
    var target = event.target;
    if (!target.matches || !target.matches('[data-role="results"]')) {
      return;
    }
    var created = target.querySelector(".ingredient-row[data-ingredient-id]");
    if (!created) {
      return;
    }
    var row = closestRow(target);
    if (row) {
      chooseComponent(row, {
        kind: "ingredient",
        ref: created.dataset.ingredientId,
        label: created.dataset.ingredientName,
        unitId: created.dataset.defaultUnitId,
      });
    }
  });
})();
