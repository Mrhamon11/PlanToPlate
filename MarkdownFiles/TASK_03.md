# Task 3: Composite Domain Structures & Asynchronous HTMX Interface Components

## Context Reference
Review `SCHEMA_SPEC.md` and `UI_ROUTES_SPEC.md` before coding.

## Objective
Build out the core schema for Ingredients and Recipes using a composite join design to allow recursive recipe nesting, and create an inline CRUD web component using asynchronous HTMX updates.

## Technical Requirements
1. **Ingredient Entity:** Create an `Ingredient` table mapping: `id`, `name`, `category` (e.g., Protein, Produce, Pantry), `isCustom` (Boolean), `ownerId` (Long, Nullable for system-wide default components), and a text block for `notes`.
2. **Recipe Entity:** Create a `Recipe` table mapping: `id`, `name`, `instructions` (Text block), `rating` (Integer), `isFavorite` (Boolean), `madeCount` (Integer), `isPublic` (Boolean), `ownerId` (Long), and a text block for `notes`.
3. **Composite Join Architecture (`RecipeItem`):** To resolve the core requirement where a recipe item can be either an ingredient or another complete sub-recipe, model a separate entity containing:
   * `id` (Primary Key)
   * `parent_recipe_id` (Foreign Key linking to parent Recipe)
   * `ingredient_id` (Foreign Key linking to Ingredient, Nullable)
   * `sub_recipe_id` (Foreign Key linking to child Recipe, Nullable)
   * `quantity` (Double), `unit` (String/Enum matching volume, mass, or counts)
   * *Business Rules Validation:* Enforce a strict service-layer constraint or data validator checking that **exactly one** field (`ingredient_id` or `sub_recipe_id`) is non-null for every record saved.
4. **Thymeleaf + HTMX View Components:** Build the web interface for managing recipes:
   * Do not use heavy single-page application frameworks. Use standard Spring controllers returning partial template layout blocks.
   * Use HTMX expressions (`hx-post`, `hx-delete`, `hx-target`, `hx-swap="outerHTML"`) to support live, dynamic row addition or row deletion of ingredients directly inside the recipe creation screen without executing a full browser reload.

## Testing & Regression Criteria (Mandatory Completion Gate)
1. **Data Model Integrity Constraints (`@DataJpaTest`):** Implement data slice tests targeting the `RecipeItem` entity:
   * Assert that attempting to save a row containing *both* an `ingredient_id` and a `sub_recipe_id` triggers a programmatic or database-level validation exception.
   * Assert that attempting to save a row containing *neither* references triggers an identical validation failure.
2. **HTMX Async Endpoint Verification (`@WebMvcTest`):** Build a controller test using `MockMvc` simulating the asynchronous additions of item rows. Assert that:
   * The returned element payload has an HTTP 200 status code.
   * The body contains only the micro-targeted Thymeleaf HTML row snippet rather than an entirely re-rendered layout frame.
3. **Regression Safety Baseline:** Execute all preceding user authentication test blocks from Task 2 to ensure core session filtering mechanics stay fully operational.

## Expected Step-by-Step Execution
1. Model the `Ingredient`, `Recipe`, and `RecipeItem` entities with validation logic.
2. Build data repositories and service layers managing basic entity mutations.
3. Write the web view controllers returning specific layout elements.
4. Construct the HTML view interface panels integrated with HTMX attributes.

## Documentation Mandate
Update your tracking specification files before concluding:
* `SCHEMA_SPEC.md`: Add comprehensive descriptions of the Ingredient, Recipe, and polymorphic RecipeItem join tables.
* `UI_ROUTES_SPEC.md`: Detail the recipe editing URL targets, focusing on the specific controller endpoints returning partial HTML fragments for HTMX swaps.