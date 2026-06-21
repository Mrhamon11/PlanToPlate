# Task 7: Admin Panel Dashboard, Native Schema Explorer, & JSON Seeding Engine

## Context Reference
Review all compiled specification sheets before writing code.

## Objective
Build a secure admin panel accessible only by administrative roles, providing direct, unsanitized low-level database visibility and automated bulk ingestion of JSON ingredient data.

## Technical Requirements
1. **Administrative Security Shield:** Enforce a strict intercept rule locking down the entire `/admin/**` routing tree to require users with `ROLE_ADMIN`.
2. **User Management Interface:** Build a dashboard view that lets an administrator provision new user accounts, toggle security flags, and assign temporary entry keys.
3. **Native Schema Table Explorer:** Build an administrative view that runs native, raw SQL lookups against SQLite, completely bypassing the standard JPA/Hibernate persistence filters. Pipe the raw column array outputs dynamically into a clean HTML table wrapper layout in Thymeleaf.
4. **Bulk JSON Ingestion Engine:** Build a processing service that handles uploading text files via the admin dashboard. The code must parse arrays matching the structure below, validate data properties, and batch-insert them cleanly into your SQLite instance:
   ```json
   [
     {
       "name": "Firm Tofu",
       "category": "Protein",
       "isCustom": false,
       "notes": "Press thoroughly before cooking to maximize texture and sauce absorption."
     },
     {
       "name": "Potato Gnocchi",
       "category": "Carb",
       "isCustom": false,
       "notes": "Can be boiled directly or pan-seared in oil for a crisp exterior."
     }
   ]
   ```

## Testing & Regression Criteria (Mandatory Completion Gate)
1. **Administrative Boundary Protection (`@WebMvcTest`):** Write rigorous controller layer tests simulating a user accessing `/admin/**` endpoints:
   * Assert that a standard user profile carrying `ROLE_USER` receives an immediate HTTP 403 Forbidden rejection.
   * Assert that an unauthenticated anonymous user falls back to a login redirection trap.
2. **Raw Schema Query Test:** Stub an admin query request passing raw SQL against standard internal structural definitions. Assert that the service layer bypasses standard Hibernate object caches and drops raw matrix string rows onto the view component framework.
3. **Bulk JSON Processing Engine Test:** Feed a mock JSON array file into your import controller using `MockMultipartFile`. Validate that:
   * Properly structured ingredients successfully write straight to the database.
   * Malformed or structurally corrupted JSON lines fail gracefully with handled log reports instead of causing application instance deadlocks.
   
## Expected Step-by-Step Execution
1. Secure the administrative route trees using Spring Security configurations.
2. Build the admin user-management layout pages and underlying service actions.
3. Implement the native query runner utility using JdbcTemplate.
4. Implement the file upload parsing engine using Jackson JSON mapping utilities.

## Documentation Mandate
Finalize all system tracking criteria:
* `SCHEMA_SPEC.md`: Perform a complete review and sign off on all database relational tables.
* `UI_ROUTES_SPEC.md`: Confirm every application view path, endpoint operation, and security policy is fully documented.