# Task 5: Aggregators, Curated Collections, & Polymorphic Flex-Lists

## Context Reference
Review `SCHEMA_SPEC.md` and `UI_ROUTES_SPEC.md` before coding.

## Objective
Build relational aggregators for organizing recipes (RecipeBooks and Dishes) along with a flexible listing container capable of mixing text notes with actual database records.

## Technical Requirements
1. **RecipeBook Aggregate:** Build a `RecipeBook` entity mapped to: `id`, `name`, `ownerId`, and a Many-to-Many association containing assigned `Recipe` objects.
2. **Dish Aggregate:** Build a `Dish` entity representing complete multi-course meal combinations (e.g., matching a main dish recipe with a side dish sub-recipe). It must track: `id`, `name`, `ownerId`, `rating`, `madeCount`, `isFavorite`, and a collection mapping assigned components.
3. **Polymorphic List Container (`GenericList`):** Build a flexible listing framework enabling users to manage mixed lists (shopping lists, menu lists, or text notes). Implement an entity configuration layout matching:
   * `GenericList`: `id`, `name`, `ownerId`, `listType` (Enum: `SHOPPING`, `MEAL_PLAN`, `CUSTOM`).
   * `ListEntry` (Child join rows containing individual items):
     * `id` (Primary Key)
     * `list_id` (Link to parent container)
     * `rawText` (String field, Nullable - used for freeform text line entries)
     * `recipe_id` (Link to data Recipe, Nullable)
     * `dish_id` (Link to data Dish, Nullable)
     * `sortOrder` (Integer)
4. **Dynamic Reordering UI:** Create the corresponding Thymeleaf management interfaces. Integrate HTMX endpoints to let users append lines, delete rows, or update specific text fields asynchronously.

## Testing & Regression Criteria (Mandatory Completion Gate)
1. **Polymorphic List Entry Persistence (`@DataJpaTest`):** Write repository tests validating the flexible container behavior of `ListEntry`:
   * Confirm that a row successfully maps and retains references to freeform `rawText` strings.
   * Confirm rows can link cleanly to distinct `Recipe` or `Dish` elements without foreign-key assignment conflicts.
2. **Ordering & Sequence Sorting Verification:** Write an explicit service test checking that fetching a `GenericList` processes its child `ListEntry` objects strictly in accordance with their assigned integer `sortOrder` values.
3. **UI Fragment Swap Security:** Use `MockMvc` to verify that executing asynchronous HTMX deletes on items securely slices elements away without forcing a structural fallback context crash.

## Expected Step-by-Step Execution
1. Build out `RecipeBook`, `Dish`, `GenericList`, and `ListEntry` JPA structures.
2. Implement repository frameworks and data manipulation business boundaries.
3. Construct the HTML list display frames using Thymeleaf structures.
4. Write the controller endpoints that handle adding and managing specific line items via HTMX.

## Documentation Mandate
Update your tracking specification files before concluding:
* `SCHEMA_SPEC.md`: Map the complete entity schemas for RecipeBook, Dish, GenericList, and the polymorphic ListEntry.
* `UI_ROUTES_SPEC.md`: Map out the routing configurations and element targets for managing lists asynchronously.