# Project: PlanToPlate - Feature Tasks & Progress Tracking (v3.x)

*Last updated: Task 2 - Authentication Logout Route Fix [COMPLETE]*

## Task 01: User Profile View Route Setup ✓ COMPLETE
- **Issue:** No route handler for `/profile/{userId}` endpoint  
- **Solution:** Created `AuthController` with `@GetMapping("/profile/{userId}")` that returns partial user profile HTML fragment via Thymeleaf
- **File Created:** [`src/main/java/com/plantoplate/controller/AuthController.java`](src/main/java/com/plantoplate/controller/AuthController.java)
  - Returns Thymeleaf template fragments at `/partials/user-profile.html`
  - Uses `hx-trigger="load"` for HTMX reactive loading
- **Fixes Added to:**
  - `SCHEMA_SPEC.md`: Documented user profile projection and controller method signatures
  - `UI_ROUTES.md`: Added partial route mapping for `/profile/{userId}` → `/partials/user-profile.html`

---

## Task 02: Authentication Logout Route Fix ✓ COMPLETE
- **Issue:** User can login successfully at `/auth/login`, but clicking logout at `/logout` throws a security exception because the controller method exists but the SecurityConfig's filter chain redirects to `/auth/logout` instead of `/logout`
- **Root Cause:** SecurityConfig had `logoutUrl("/auth/logout")` but frontend links point to `/logout`
- **Solution:** Updated [`SecurityConfig.java`](src/main/java/com/plantoplate/config/SecurityConfig.java):
  - Changed `.requestMatchers()` from `/auth/logout` → `/logout`
  - Changed `.logoutUrl()` from `/auth/logout` → `/logout`
- **Fixes Added to:**
  - `SCHEMA_SPEC.md`: Documented SecurityFilterChain authorization configuration for logout endpoint
  - `UI_ROUTES.md`: Updated auth filter chain documentation with corrected logout URL mappings

---

## Task 03: Authentication Reset Password Route Setup ✓ COMPLETE
- **Issue:** No route handler for `/auth/reset-password` endpoint  
- **Solution:** Created `AuthController` method at `/auth/reset-password` that renders reset password UI fragment via Thymeleaf
- **File Created:** [`src/main/java/com/plantoplate/controller/AuthController.java`](src/main/java/com/plantoplate/controller/AuthController.java)
  - Returns partial HTML at `/partials/reset-password.html`
  - Validates current temp password before allowing new password reset
- **Fixes Added to:**
  - `SCHEMA_SPEC.md`: Documented authentication controller method signatures for password reset flow
  - `UI_ROUTES.md`: Added auth fragment route mapping for password reset endpoint

---

## Task 04: User Profile Data Projection (Future) 🔜 PLANNED
- **Description:** Create lean JPA projection for user profile data retrieval
- **Note:** Not yet implemented; will extract minimal fields (username, email, name) from Users entity

---

## Key Files Modified or Created This Turn:

### 1. [`src/main/java/com/plantoplate/controller/AuthController.java`](src/main/java/com/plantoplate/controller/AuthController.java)
**Purpose:** New controller handling user profile view and authentication-related routes

**Methods Added:**
- `@GetMapping("/profile/{userId}")` - Returns user profile partial HTML via Thymeleaf
- `@PostMapping("/update-preferences")` - Handles preference updates with validation
- `@GetMapping("/auth/reset-password")` - Renders reset password form for temp passwords

---

### 2. [`src/main/java/com/plantoplate/config/SecurityConfig.java`](src/main/java/com/plantoplate/config/SecurityConfig.java)
**Purpose:** Fix logout route to match frontend expectations

**Changes Made:**
- Updated security filter chain to permit requests to `/logout` instead of `/auth/logout`
- Changed `logoutUrl("/logout")` to match the URL used in frontend logout links

---

## Database & Schema Specifications (from SCHEMA_SPEC.md):

### Users Entity Fields:
| Field | Type | Description |
|-------|------|-------------|
| userId | Long | Primary key for user accounts |
| username | String | Unique login identifier |
| email | String | User email address |
| passwordHash | String | BCrypt encoded credentials |
| isTempPassword | Boolean | Flag for temporary login passwords |

### SecurityFilterChain Configuration:
- Login page: `/auth/login` (permits all)
- Logout endpoint: `/logout` (permits all, invalidates session)
- Password reset: `/auth/reset-password` (permits all)
- All other requests require authentication

---

## UI Route Mappings (from UI_ROUTES.md):

### Authentication Routes:
| Method | URL | Description | Template/Response |
|--------|-----|-------------|------------------|
| GET | `/auth/login` | Login page | `login.html` |
| POST | `/auth/login` | Process login | Redirect to home/error |
| GET | `/logout` | Logout session | Redirect to home |

### User Profile Routes:
| Method | URL | Description | Template/Response |
|--------|-----|-------------|------------------|
| GET | `/profile/{userId}` | View user profile | `/partials/user-profile.html` |

---

## Testing Checklist (Task 2):
- [x] Login at `/auth/login` works
- [x] Logout at `/logout` now works correctly
- [x] SecurityConfig updated to use `/logout` URL
- [ ] End-to-end: Verify session is cleared on logout
