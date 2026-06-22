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

### Milestone 1: Core Base & Security Infrastructure
* [x] **Task 1:** Project Skeleton, SQLite WAL Provisioning, & Base Layout Setup ✅
* [x] **Task 2:** RBAC Security, Persistent Session Management, & Temp Password Lifecycle ✅

### Milestone 2: Relational Domain & Async Interface
* [ ] **Task 3:** Composite Ingredient/Recipe Schema & Inline HTMX CRUD Engine
* [ ] **Task 4:** Row-Level Authorization Safeguards & Recursive Entity Deep-Copy Engine

### Milestone 3: Collections & Scheduling Engines
* [ ] **Task 5:** RecipeBooks, Dishes, and Polymorphic Flex-Lists Containers
* [ ] **Task 6:** Parameterized Meal Planning Selection Algorithm & Shopping List Consolidation

### Milestone 4: Governance & Seed Ingestion
* [ ] **Task 7:** Admin Control Hub, Direct Schema Table Explorer, & Bulk JSON File Importer

## Task 2 Completion Summary - Implemented Components

| Component | Status | Description |
|-----------|--------|-------------|
| `User` Entity | ✅ Complete | JPA entity with id, username, passwordHash, role (ADMIN/USER), isTempPassword |
| `UserRepository` | ✅ Complete | JpaRepository extending basic CRUD + findByUsername() method |
| `PlanToPlateUserDetailsService` | ✅ Complete | Spring Security UserDetailsService implementation with BCrypt |
| `BCryptPasswordEncoder` Bean | ✅ Complete | Password encoder bean registered in SecurityConfig |
| `TempPasswordInterceptor` | ✅ Complete | Filter intercepting requests, redirects temp-password users to reset page |
| `AuthenticationController` | ✅ Complete | Login, logout, reset-password GET/POST handlers with session management |
| `SecurityConfig` | ✅ Complete | Spring Security configuration with filter chain, form login, logout setup |
| `templates/login.html` | ✅ Complete | Thymeleaf login form with error/message attributes |
| `templates/reset-password.html` | ✅ Complete | Thymeleaf password reset form with current/new password fields |
| `templates/fragments/layout.html` | ✅ Complete | Master layout with navigation, content fragment (th:block), footer |
| `templates/index.html` | ✅ Complete | Root page content for HTMX async rendering |
| UserServiceBCryptTest | ✅ PASSING (5 tests) | Password hashing, username normalization, role handling, temp flag |
| PlanToPlateIntegrationTest | ✅ PASSING (1 test) | End-to-end integration verification |

---
*Last updated: Task 2 - All Task 2 deliverables [COMPLETE] / Maven Build & Test Suite Stable [6/6 tests PASS]*
