# Task 1: Project Skeleton, SQLite WAL Configuration, & UI Master Template

## Objective
Establish the initial Spring Boot 3.x file system architecture targeting Java 21, configure SQLite for multi-threaded access without thread-locking exceptions, enable JVM virtual threads for high-concurrency hypermedia rendering, and build the parent Thymeleaf responsive template layout embedded with HTMX and Tailwind CSS.

## Technical Requirements
1. **Java Version:** Initialize the Maven or Gradle build environment strictly targeting **Java 21 (LTS)**. Ensure the `<java.version>` build property is explicitly set to `21`.
2. **Dependencies:** Initialize a Spring Boot 3.x project containing the following starter core modules:
   * `spring-boot-starter-web`
   * `spring-boot-starter-data-jpa`
   * `spring-boot-starter-thymeleaf`
   * `spring-boot-starter-validation`
   * `lombok`
3. **Database Driver:** Add the standard SQLite JDBC driver (`org.xerial:sqlite-jdbc`) and the official Hibernate community dialect (`org.hibernate.community.dialect.SQLiteDialect`) to your dependency tree.
4. **Application Properties:** Configure `src/main/resources/application.yml` to enable JVM Virtual Threads (Project Loom), force SQLite Write-Ahead Logging (WAL) mode, and support automated Hibernate entity schema tracking:
   ```yaml
   spring:
     threads:
       virtual:
         enabled: true
     datasource:
       url: jdbc:sqlite:plantoplate.db?journal_mode=WAL&busy_timeout=5000
       driver-class-name: org.sqlite.JDBC
     jpa:
       database-platform: org.hibernate.community.dialect.SQLiteDialect
       hibernate:
         ddl-auto: update
       show-sql: true
   ```
5. **Master Layout UI**: Create `src/main/resources/templates/fragments/layout.html`. This file must act as the layout template framework for the entire application web interface.
   * Include standard semantic HTML5 boilerplate attributes.
   * Import HTMX via official CDN (`https://unpkg.com/htmx.org`).
   * Import Tailwind CSS via utility CDN (`https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4`).
   * Define a primary structural main content fragment tag (`th:fragment="content"`) that is completely mobile-responsive, touch-friendly, and viewport-optimized.

## Testing & Regression Criteria (Mandatory Completion Gate)
1. **Application Context Boot Test:** Write a standard Spring Boot integration test (`@SpringBootTest`) ensuring the global configuration context initializes flawlessly without throwing database setup bean initialization errors.
2. **SQLite WAL Mode Verification:** Include a programmatic test or context startup log validation asserting that the database connection pool successfully provisions the active connection with `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=5000;`.
3. **Template Resolution Test:** Write a minimal web slice controller test (`@WebMvcTest`) ensuring that incoming traffic requests to static/root paths successfully resolve and render the base structural HTML layout frame instead of throwing Thymeleaf parsing exceptions.

## Expected Step-by-Step Execution
1. Generate the initial Spring Boot 3.x project folder directory layout targeting Java 21 via your build configuration.
2. Formulate the comprehensive application-wide properties `application.yml` file to initialize virtual threads and SQLite WAL parameters.
3. Write a baseline integration test to verify that an unblocked connection thread cleanly initializes to the embedded `plantoplate.db` data asset.
4. Implement the master Thymeleaf layout page wrapper file utilizing Tailwind framing styles and loading the global HTMX script asset.

## Documentation Mandate
Before marking this task complete, you must initialize and save two documentation files in the root project folder to act as context boundaries for subsequent steps:
* `SCHEMA_SPEC.md`: Document the initial Java environment details, active build profile properties, SQLite URL configurations, and Hibernate dialects.
* `UI_ROUTES_SPEC.md`: Document the master template layout locations and Thymeleaf fragment identifier paths.

## Completion Status: ✅ COMPLETE
- **Task Executed:** All requirements met on branch `feature/task-1-initial-skeleton`
- **Build Verification:** Maven `mvn clean test` → BUILD SUCCESS (4 tests, 0 failures)
- **Artifacts Produced:**
  - `pom.xml`: Java 21 + Spring Boot 3.4.1 + SQLite JDBC
  - `application.yml`: Virtual threads + WAL mode configured
  - `PlantToPlateApplication.java`: Entry point with Spring Data JPA
  - `HomeController.java`: Root path controller (`/` → index view)
  - `templates/index.html`: Landing page view
  - `templates/fragments/layout.html`: Master Thymeleaf layout (HTMX + Tailwind CDNs)
  - `PlantToPlateIntegrationTest.java`: Context init test (PASSING)
  - `HomeControllerWebMvcTest.java`: Template resolution tests (3 PASSING)
  - `SCHEMA_SPEC.md`: Build config documentation
  - `UI_ROUTES_SPEC.md`: Route mapping documentation
- **Git Commit:** [c8733af](https://github.com/Mrhamon11/PlanToPlate/commit/c8733af) - Task 1 commit on `master`
- **Feature Branch:** `feature/task-1-initial-skeleton` pushed to remote
- **PR Link:** https://github.com/Mrhamon11/PlanToPlate/pull/new/feature/task-1-initial-skeleton