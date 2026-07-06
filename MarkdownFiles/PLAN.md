# PlanToPlate Master Plan

## Architectural Overview
* **Framework:** Django 5.x
* **Frontend:** Django Templates augmented with HTMX for reactive, single-page-app-like interactions without JavaScript bloat.
* **API Engine:** Django REST Framework (DRF) to expose decoupled, secure endpoints for potential future native client consumers.
* **Database:** SQLite running in WAL (Write-Ahead Logging) mode for robust concurrency handling. Abstracted fully by Django ORM to allow transparent future migration to PostgreSQL via environment variables.

---

## Revised Execution Roadmap

### Phase 1: Foundation, Security & Isolation
* [ ] **Task 1.1:** Core Project Initialization, Database Tuning, and Basic Layout
* [ ] **Task 1.2:** Authentication, Custom User Model, and Multi-Tenant Privacy Architecture

### Phase 2: Core Culinary Components
* [ ] **Task 2.1:** Ingredient Database Management & Unit Normalization
* [ ] **Task 2.2:** Recipe Management & Nested Ingredient Composition

### Phase 3: Aggregation & Organization
* [ ] **Task 3.1:** Dishes (Meal Component Grouping)
* [ ] **Task 3.2:** Custom RecipeBooks Management
* [ ] **Task 3.3:** Generic Lists Framework (Shopping, Menu, Notes)

### Phase 4: Intelligence & Control
* [ ] **Task 4.1:** Automated Meal Planner & Constraint Tagging Engine
* [ ] **Task 4.2:** Admin Dashboard & Django-Import-Export JSON Pipeline

### Phase 5: Sharing & Collaboration Network
* [ ] **Task 5.1:** Read-Only Granular Permission and Object Sharing Engine
* [ ] **Task 5.2:** Social Feed Feed & Object Cloning Architecture

---

## Design Safeguards & Conventions
1. **Multi-Tenancy:** Every model data-query must default to filtering by the authenticated user session context unless an object is flagged explicitly as public or shared.
2. **HTMX Responses:** Views handling HTMX requests must return semantic micro-HTML fragments instead of complete HTML boilerplate documents.
3. **API Contracts:** Every completed backend task must update its local documentation block to ensure the LLM retains absolute context of existing database states and operational logic without parsing entire raw code files.