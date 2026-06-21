# Task 2: Authentication Infrastructure, Secure Session Management, & Temp Credentials Workflows

## Context Reference
Review `SCHEMA_SPEC.md` and `UI_ROUTES_SPEC.md` before coding.

## Objective
Implement secure user storage, password encryption via BCrypt, stateful session cookie tracking, and a mandatory redirection interception workflow for temporary administrative passwords.

## Technical Requirements
1. **Security Dependency:** Integrate `spring-boot-starter-security` and `thymeleaf-extras-springsecurity6`.
2. **User Data Model:** Build a relational `User` entity containing:
   * `id` (Long, Primary Key)
   * `username` (String, Unique, Indexed)
   * `passwordHash` (String)
   * `role` (Enum: `ADMIN`, `USER`)
   * `isTempPassword` (Boolean)
3. **Spring Security Engine:** Configure stateful authentication tracking using standard HTTP session cookies (`JSESSIONID`). Wire up persistent session mechanisms (Remember-Me strategy) to maintain active states across browser restarts.
4. **Temporary Password Interceptor:** Write a custom web request filter or handler interceptor. If an authenticated user has `isTempPassword == true`, block access to all standard URLs and force a visual redirection to a password modification view (`/auth/reset-password`).
5. **View Layers:** Generate clean, responsive templates:
   * `templates/login.html`: Standard secure user sign-in workspace layout.
   * `templates/reset-password.html`: Forceful password updating workspace.

## Testing & Regression Criteria (Mandatory Completion Gate)
1. **Password Hashing Unit Test:** Implement a service-level JUnit test asserting that raw passwords passed into user registration models are non-trivially scrambled via BCrypt, and verify that the raw plain text is never persisted.
2. **Web Security Slice Testing (`@WebMvcTest`):** Leverage `MockMvc` alongside Spring Security test libraries to verify:
   * Anonymous unauthenticated requests to protected paths drop an immediate HTTP 302 redirect targeting `/login`.
   * Authenticated sessions containing standard cookies maintain state over subsequent dummy request dispatches.
3. **Temporary Password Interceptor Assertions:** Mock an authenticated profile where `isTempPassword = true`. Assert that attempts to target the main app routes yield a hard redirect directly back onto `/auth/reset-password`.

## Expected Step-by-Step Execution
1. Create the `User` JPA entity and corresponding `UserRepository`.
2. Code the custom `UserDetailsService` using `BCryptPasswordEncoder`.
3. Construct the Spring Security filter chain block.
4. Implement the temporary password validation interceptor mechanism.
5. Create the login and reset Thymeleaf layout forms.

## Documentation Mandate
Update your tracking specification files before concluding:
* `SCHEMA_SPEC.md`: Define the `User` schema fields, indexes, and constraint conditions.
* `UI_ROUTES_SPEC.md`: Document `/login`, `/logout`, and `/auth/reset-password` paths, including the exact session security requirements for each.