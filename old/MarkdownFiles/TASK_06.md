# Task 6: Parameterized Scheduling Logic & Auto-Shopping Consolidation

## Context Reference
Review `SCHEMA_SPEC.md` and `UI_ROUTES_SPEC.md` before coding.

## Objective
Write the algorithmic core responsible for generating automated meal schedules based on user constraints, and recursively resolve all required components into a single, consolidated shopping list.

## Technical Requirements
1. **Meal Planning Request Contract:** Create a request validation data object containing:
   * `daysToGenerate` (Integer)
   * `targetComposition` (Enum: `PROTEIN_CARB_VEG`, `ONE_POT`)
   * `categoryConstraints` (Map tracking max occurrences for specified categories, e.g., `{"Pork": 1, "Chicken": 2}`)
2. **Selection Core Logic Engine:** Write a service algorithm that accepts the parameter contract:
   * Filter the global database to compile all Recipes and Dishes readable by the current session user.
   * Randomly assemble items into target day slots, tracking running counts of structural tags and ingredient classifications to ensure that none exceed the user's maximum occurrence limits.
3. **Recursive Ingredient Consolidator:** Write an automation service layer:
   * Once a meal schedule configuration is accepted by the user, extract every associated recipe item.
   * Recursively traverse nested sub-recipe dependencies down until you reach only base ingredients.
   * Aggregate matching items together by calculating matching unit values (e.g., merge 100g of tofu with 250g of tofu to produce a single line entry for 350g of tofu).
   * Automatically generate and populate a new instance inside the `GenericList` framework labeled "Shopping List - [Date]" containing the consolidated items.
4. **Interactive Dashboard Interface:** Render the calendar layout inside Thymeleaf. Use HTMX attributes to let users click single calendar day slots to selectively cycle or shuffle that specific menu item without disrupting the rest of the generated week.

## Testing & Regression Criteria (Mandatory Completion Gate)
1. **Algorithmic Constraint Assertions:** Write a randomized logic stress test for the meal planner engine. Generate a sequence of 100 schedules using hard limit rules (e.g., max 1 chicken meal per cycle) and mathematically verify that the generation matrix never breaks the boundary ceilings.
2. **Recursive Traversal Resolution Test:** Seed a mock dish that relies on a composite sub-recipe (which itself holds raw base ingredients). Run the list generator and assert that the output completely resolves the complex tree structures down to flat, un-nested ingredient assets.
3. **Ingredient Volume Aggregation Verification:** Seed a meal plan requiring multiple distinct ingredients of identical configurations (e.g., 100 grams of tofu for lunch, 250 grams for dinner). Validate that the shopping compiler sums them cleanly into a single entry of 350 grams.

## Expected Step-by-Step Execution
1. Code the scheduling configuration data contracts.
2. Write the selection algorithm logic alongside comprehensive unit validation tests.
3. Write the recursive ingredient consolidation engine.
4. Connect the generation pipelines to the UI dashboard using HTMX controls.

## Documentation Mandate
Update your tracking specification files before concluding:
* `SCHEMA_SPEC.md`: Document any temporary data constructs or algorithmic parameters needed.
* `UI_ROUTES_SPEC.md`: Document the specific control actions for `POST /meal-plan/generate` and the individual calendar shuffling pathways.