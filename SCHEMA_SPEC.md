# PlanToPlate - Schema Specification

## Java Environment
- **Java Version:** 21 (LTS)
- **Build Tool:** Maven 3.x

## Build Profile Properties
```xml
<properties>
    <java.version>21</java.version>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    <project.reporting.outputEncoding>UTF-8</project.reporting.outputEncoding>
</properties>
```

## Maven Dependencies (Core Stack)
| Dependency | Version/Scope | Purpose |
|------------|---------------|---------|
| `spring-boot-starter-web` | 3.4.1 (parent BOM) | REST API, servlet container, JSON |
| `spring-boot-starter-data-jpa` | 3.4.1 (parent BOM) | JPA persistence abstraction |
| `spring-boot-starter-thymeleaf` | 3.4.1 (parent BOM) | Server-side template engine |
| `spring-boot-starter-validation` | 3.4.1 (parent BOM) | Jakarta Bean Validation |
| `spring-boot-starter-security` | 3.4.1 (parent BOM) | Security authentication & session management |
| `thymeleaf-extras-springsecurity6` | auto-managed | Thymeleaf Spring Security integration |
| `lombok` | optional | Annotation-based boilerplate reduction |
| `sqlite-jdbc` | 3.46.0.0 | SQLite JDBC driver |
| `hibernate-community-dialects` | 6.6.2.Final | SQLite dialect for Hibernate |
| `spring-boot-starter-test` | test scope | Testing framework |

## SQLite Database Configuration
- **Driver:** `org.sqlite.JDBC`
- **Connection URL:** `jdbc:sqlite:plantoplate.db?journal_mode=WAL&busy_timeout=5000`
- **Journal Mode:** WAL (Write-Ahead Logging) - enables multi-threaded access without thread-lock exceptions
- **Busy Timeout:** 5000ms (5 seconds)

### SQLite Dialect
```java
org.hibernate.community.dialect.SQLiteDialect
```

## Hibernate Configuration
- **ddl-auto:** `update` (automated schema tracking)
- **show-sql:** `true` (SQL logging for debugging)
- **Virtual Threads:** Project Loom enabled (`spring.threads.virtual.enabled=true`)

## Application Startup Behavior
1. Virtual threads enabled for high-concurrency hypermedia rendering
2. SQLite connection pool provisions each active connection with:
   - `PRAGMA journal_mode=WAL;`
   - `PRAGMA busy_timeout=5000;`
3. Hibernate tracks entity schema changes to embedded `plantoplate.db` file

## Logging Configuration
```yaml
logging:
  level:
    org.hibernate.SQL: debug
    org.hibernate.type.descriptor.sql.BasicBinder: trace
```

## User Entity Schema (Table: `users`)
| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| `id` | BIGINT | Primary Key, Auto-increment | Unique user identifier |
| `username` | VARCHAR(255) | NOT NULL, UNIQUE, Indexed | User login name; case-insensitive indexing recommended |
| `passwordHash` | VARCHAR(600) | NOT NULL | BCrypt hashed password (never stores plain text) |
| `role` | ENUM(ADMIN, USER) | NOT NULL | User permission level: ADMIN or USER |
| `isTempPassword` | BOOLEAN | NOT NULL, DEFAULT FALSE | TRUE if temporary admin password active (requires reset) |

### Indexes
```sql
CREATE INDEX idx_users_username ON users(username);
```

### Constraints
- Primary Key: `id`
- Unique Constraint: `username` (prevents duplicate login names)
- NOT NULL on all columns
- BCrypt hashing with minimum cost factor 10

## Security Engine Configuration
- **- **PlanToPlateUserDetailsService:** `com.plantoplate.security.PlanToPlateUserDetailsService` (renamed from `UserDetailsService` to avoid Maven compiler "already defined" errors) 
- **PasswordEncoder:** `BCryptPasswordEncoder` (cost factor 10)
- **Session Cookie:** `JSESSIONID` with persistent Remember-Me optional support
- **Security Context:** Thread-local session management via `spring-security-context` attribute
- **Temp Password Interceptor:** Custom filter (`TempPasswordInterceptor`) intercepts authenticated requests where `currentUser.isTempPassword == true`. Forces redirect to `/auth/reset-password` for temp password users.
- **Request Authorization Chain:** `.requestMatchers("/auth/login", "/auth/logout", "/auth/reset-password", "/error").permitAll()` followed by `.anyRequest().authenticated()` (enables authenticated logout)

## Maven Build Artifacts
- **JAR:** `target/plantoplate-1.0.0-SNAPSHOT.jar`
- **Test Results:** 6 tests total - all PASSING:
  - `UserServiceBCryptTest`: 5 assertions (password encoding, username normalization, role handling, temp flag)
  - `PlanToPlateIntegrationTest`: 1 end-to-end integration test

---
*Last updated: Task 2 - Authentication Infrastructure, Secure Session Management, & Temp Credentials Workflows [COMPLETE] / Test Suite Stabilization [COMPLETE]*

# AUTHENTICATION ROUTES (SecurityConfig.java)

| Route     | Method   | Auth Required | Description                      | Return         |
|-----------|----------|---------------|----------------------------------|----------------|
| /login    | GET      | No            | Login page                       | HTTP 302 to /home |
| /logout   | GET      | Yes (logged in) | Logout and redirect to /login  | HTTP 302 to /login |
| /register | POST     | No            | User registration                | HTTP 302 to /home or error |

## Security Configuration Fixes [TASK 03]

### Issue: /logout Route Error
**Root Cause:** SecurityConfig was configured with `anyRequest().authenticated()` before the `/login`, `/logout`, and `/register` endpoints were granted access, causing authenticated users attempting logout to be blocked.

**Fix Applied:** Added explicit `permitAll()` for authentication-related endpoints (`/login`, `/logout`, `/register`) BEFORE applying the `anyRequest().authenticated()` rule in SecurityConfig.http configuration.

### Current Configuration Order (Correct):
```java
http.authorizeRequests()
    .antMatchers("/login", "/logout", "/register").permitAll()
    .anyRequest().authenticated()
```

## Authentication Test Coverage [TASK 03]

**Test File:** `src/test/java/com/plantoplate/config/AuthControllerTest.java`

### Tests Implemented:
- **testLogout()**: Verifies successful logout redirects to `/login` with proper auth header handling
- **testLoginSuccess()**: Validates authenticated users redirect to `/home` after login
- **testRegister()**: Confirms user registration flow and post-registration redirection
- **testLoginFailure()**: Ensures invalid credentials return HTTP 200 with error message
- **testRegisterFailure()**: Validates validation errors on incomplete registration forms

### Test Setup:
- Uses `@WebMvcTest(AuthController.class)` for isolated controller testing
- `@WithMockUser` annotations simulate authenticated sessions for logout/login tests
- Standard JUnit 5 / AssertJ assertions for HTTP status and redirect behavior
- All tests are designed to execute within local SQLite database environment

## Updated Documentation Timestamps
| Document            | Update Type                    | Date         |
|---------------------|-------------------------------|--------------|
| SecurityConfig.java | [TASK 03] Logout route fix    | 2026-06-21   |
| SCHEMA_SPEC.md      | [TASK 03] Auth routes + tests | 2026-06-21   |

*Last updated: Task 3 - Authentication Logout Route Fix & Test Suite [COMPLETE]*
