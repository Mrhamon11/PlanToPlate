# Task 4: Row-Level Authorization Safeguards & Recursive Entity Deep-Copy Engine

## Context Reference
Review `SCHEMA_SPEC.md` and `UI_ROUTES_SPEC.md` before coding.

## Objective
Secure database entries so users can only access authorized assets, and implement a recursive deep-copy engine that safely duplicates shared recipes across accounts.

## Technical Requirements
1. **Access Mapping Storage:** Create a `PermissionMapping` entity containing: `id`, `entityType` (String representation, e.g., "RECIPE"), `entityId` (Long), and `userId` (Long) to record granular data-sharing access rules.
2. **Data Security Interceptors:** Update or wrap all repository read operations on Recipes and Ingredients to ensure row-level access verification. A user may only see an object if:
   * They are the explicit owner (`ownerId` matches current session user).
   * The entity is globally accessible (`isPublic == true`).
   * A valid relationship is present within the `PermissionMapping` table.
   * If any user attempts to modify or delete a resource they do not explicitly own, immediately throw an AccessDeniedException.
3. **Recursive Deep-Copy Service:** Build a service class that handles copying an asset to a new user account:
   * When an authorized user executes a clone action on a shared recipe, generate a completely unique Recipe database entry mapping the new user's ID as the `ownerId`.
   * The engine must recursively traverse the original recipe's collections and create duplicate entries for all associated `RecipeItem` links.
   * If a sub-recipe inside that collection is not owned by the copier and is private, copy it recursively as well.
   * Ensure that the original source entity records remain entirely unmutated.
4. **Interface Integration:** Expose the feature via an HTMX element (`hx-post="/recipes/{id}/copy"`) that duplicates the shared recipe and immediately appends it to the user's dashboard view.

## Testing & Regression Criteria (Mandatory Completion Gate)
1. **Row-Level Isolation Assertions:** Mock two separate testing profiles (e.g., User A and User B). Write security service tests verifying that:
   * User B attempting to read a completely private recipe owned by User A immediately triggers a clean `AccessDeniedException` or an empty resource wrapper return.
   * User B attempting to modify or delete a public asset owned by User A triggers an explicit modification restriction block.
2. **Recursive Deep-Copy Unit Test:** Write a transactional service test executing a recipe clone process. Assert that:
   * The new Recipe object has its `ownerId` assigned to the active copier.
   * All child elements (`RecipeItem` entries) are given entirely distinct primary key identifiers from their originals.
   * Modifying fields inside the cloned recipe structure does not mutate the source records in any capacity.

## Expected Step-by-Step Execution
1. Build the permission table structures and access query modification rules.
2. Write unit security assertions confirming cross-user data isolation.
3. Implement the recursive business cloning routine inside the service layer.
4. Connect the copy routine to the UI using HTMX triggers.

## Documentation Mandate
Update your tracking specification files before concluding:
* `SCHEMA_SPEC.md`: Detail the structural design of the `PermissionMapping` entity.
* `UI_ROUTES_SPEC.md`: Document the specific access rules for `/recipes/{id}/copy`.