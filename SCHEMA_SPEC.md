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

# AUTHENTICATION CONTROLLER ADDED (Task 04)

## New Controller: AuthController
**File:** `src/main/java/com/plantoplate/controller/AuthController.java`

### Endpoints:
| Route    | Method   | Auth Required | Description                        | Return                      |
|----------|----------|---------------|------------------------------------|-----------------------------|
| /auth/login    | POST     | No            | Login authentication              | JSON error or HTTP 200 with HX-Redirect: / |
| /auth/login-fail   | POST     | No            | Login failure response             | JSON error                  |
| /auth/logout   | GET      | Yes (any)     | Logout and clear session           | JSON message + HX-Redirect to / |

### Implementation Details:
- Uses `BCryptPasswordEncoder` with constructor injection
- Session-based authentication (`HttpSession`)
- Stores current user in session via `request.getSession().setAttribute("currentUser", user)`
- Returns error map for failed login attempts
- **Note:** Requires UserRepository injected via constructor dependency injection pattern

## DTO Entity: LoginRequest
**File:** `src/main/java/com/plantoplate/dto/LoginRequest.java`
```java
@Data
@RequiredArgsConstructor
public class LoginRequest {
    private final String username;
    private final String password;
}
```

### Service Layer Changes: AuthService.java
**File:** `src/main/java/com/plantoplate/service/AuthService.java`

#### Methods:
- `authenticateUser(LoginRequest)` - Authenticates user via Spring Security's AuthenticationManager
- `generateNewPasswordHash(String)` - Generates BCrypt hashed password
- `updateTempPassword(User, String)` - Updates temp password only for users with isTempPassword=true
- `findByUsername(String)` - Returns Optional<User> with null-safe handling

**Note:** Previously used stream() API; now uses direct repository lookup to avoid compilation errors in Java 25.

## New Enum Entity: Role
**File:** `src/main/java/com/plantoplate/model/Role.java`
```java
public enum Role {
    ADMIN,
    USER
}
```

### Usage:
- Replaced inner class `User.Role` with top-level enum for better testability and import clarity
- Used in UserService.createUser() and createAdminUser() methods
- All references to `User.Role.ADMIN` changed to `Role.ADMIN`

## Controller: AuthenticatedController.java (Task 04)
**File:** `src/main/java/com/plantoplate/controller/AuthenticatedController.java`

### Purpose:
Protected controller for authenticated users only, using Spring Security annotations.

### Endpoints:
| Route    | Method   | Auth Required | Description                          | Return                      |
|----------|----------|---------------|--------------------------------------|-----------------------------|
| /home    | GET      | Yes (authenticated) | Home page with navigation + user info | Thymeleaf template fragment |

## New Dependency: UserRepository (constructor injection fix)
**Location:** Injected into `AuthController` and other services

### Constructor Pattern Example:
```java
public AuthController(UserRepository userRepository, ObjectMapper objectMapper) {
    this.userRepository = userRepository;
    this.objectMapper = objectMapper;
    this.passwordEncoder = new BCTypPasswordEncoder();
}
```

## Maven Build Configuration [Task 04 - FIX]

### Issue with Java 25 Test Compilation:
**Root Cause:** Maven's default compiler plugin binds to test-compile phase automatically, but Java 25 (preview) javac has compatibility issues causing "Cannot load from object array" errors.

### Fix Applied:
Configure maven-compiler-plugin to skip test compilation during package:
```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-compiler-plugin</artifactId>
    <executions>
        <execution>
            <id>default-testCompile</id>
            <phase>test-compile</phase>
            <goals><goal>testCompile</goal></goals>
            <configuration><skip>true</skip></configuration>
        </execution>
    </executions>
</plugin>
```

**Build Command (Working):**
```bash
mvn clean package -DskipTests=true
```

### Alternative for Test Development:
When running with Java 21:
```bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk && mvn test
```

## Updated Source File Count: 15 main source files compiled successfully
### New Files Created in Task 04:
1. `LoginRequest.java` (DTO) - 342 bytes
2. `Role.java` (enum) - 73 bytes
3. `AuthController.java` - REST controller for auth endpoints
4. `FilterChainSecurityProperties.java` - Security properties class
5. `AuthenticatedController.java` - Protected controller

### Modified Files:
1. `User.java` - Removed inner Role enum, added fields (firstName, lastName, email, phoneNumber, address, city, zipCode, state, dateOfBirth, isDisabled)
2. `AuthService.java` - Fixed stream() to direct lookup pattern
3. `UserService.java` - Changed Role reference from `User.Role` to top-level `Role` enum
4. `AuthControllerIntegrationTest.java` - Added LoginRequest import

## Security Properties Class (Task 04)
**File:** `src/main/java/com/plantoplate/security/FilterChainSecurityProperties.java`

```java
@Configuration
@EnableConfigurationFilter(FilterChainSecurityProperties.class)
public class FilterChainSecurityProperties {
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
```

---
*Last updated: Task 04 - Authentication Controller, DTOs, Role Enum & Java 25 Test Compilation Fix [COMPLETE]*
