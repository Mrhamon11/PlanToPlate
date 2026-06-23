# PlanToPlate (P2P) - Master Architectural Plan

## Tech Stack Definition
* **Backend Platform:** Java 21 (LTS) / Spring Boot 3.x Spring Data JPA, Spring Security
* **Frontend Architecture:** Thymeleaf Template Engine, HTMX (via CDN), Tailwind CSS (via CDN)
* **Concurrency:** Spring Virtual Threads (Project Loom) enabled
* **Frontend:** Thymeleaf Templates + HTMX (Asynchronous Hypermedia)
* **Database:** SQLite (Embedded single-file, WAL mode optimized)

## Architecture Rules for AI Agent
1. **Concurrency Protection:** SQLite must be explicitly configured in Write-Ahead Logging (WAL) mode with a 5000ms busy timeout to prevent thread lock exceptions during asynchronous HTMX requests.
2. **Context Preservation:** At the conclusion of every single task, you must update two central documentation files: `SCHEMA_SPEC.md` and `UI_ROUTES_SPEC.md`. This ensures that subsequent tasks can be executed without forcing the model to re-parse raw source code.
3. **No Placeholders:** All generated code must be production-ready and fully articulated. Do not use generic omissions or `// TODO` comments.

## Milestone Tracker

### Milestone 1: Core Base & Security Infrastructure ✅ COMPLETE
* [x] **Task 1:** Project Skeleton, SQLite WAL Provisioning, & Base Layout Setup ✅
* [x] **Task 2:** RBAC Security, Persistent Session Management, & Temp Password Lifecycle ✅

#### Task 2 - Complete Deliverables (All Requirements Met):
- ✅ `User` JPA entity with id, username, passwordHash, role (ADMIN/USER), isTempPassword
- ✅ `UserRepository` interface extending JpaRepository with findByUsername()
- ✅ `PlanToPlateUserDetailsService` Spring Security UserDetailsService implementation
- ✅ `BCryptPasswordEncoder` bean for password hashing
- ✅ `TempPasswordInterceptor` filter redirecting temp-password users to reset page
- ✅ `AuthenticationController` with login, logout, reset-password handlers
- ✅ `SecurityConfig` with form login, logout, and temp password interceptor
- ✅ Thymeleaf templates: login.html, reset-password.html, fragments/layout.html, index.html
- ✅ UserService bean for user creation and admin seeding on startup
- ✅ CommandLineRunner in PlanToPlateApplication to seed admin user at startup
- ✅ All 6 tests passing (UserServiceBCryptTest: 5 assertions, PlanToPlateIntegrationTest: 1)
- ✅ Maven BUILD SUCCESS

### Milestone 2: Relational Domain & Async Interface
* [ ] **Task 3:** Composite Ingredient/Recipe Schema & Inline HTMX CRUD Engine
* [ ] **Task 4:** Row-Level Authorization Safeguards & Recursive Entity Deep-Copy Engine

### Milestone 3: Collections & Scheduling Engines
* [ ] **Task 5:** RecipeBooks, Dishes, and Polymorphic Flex-Lists Containers
* [ ] **Task 6:** Parameterized Meal Planning Selection Algorithm & Shopping List Consolidation

### Milestone 4: Governance & Seed Ingestion
* [ ] **Task 7:** Admin Control Hub, Direct Schema Table Explorer, & Bulk JSON File Importer

---
*Last updated: Task 2 COMPLETE / All Authentication Infrastructure Deliverables VERIFIED / Test Suite STABLE (6/6 tests PASSING)*
