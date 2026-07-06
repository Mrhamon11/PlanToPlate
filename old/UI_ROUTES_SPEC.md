# PlanToPlate - UI Routes Specification

## Template Engine
- **Engine:** Thymeleaf 3.x
- **Mode:** Server-side rendering with HTMX async support

## Directory Structure
```
src/main/resources/templates/
├── fragments/
│   └── layout.html          # Master template (shared layout framework)
├── index.html               # Root page view
└── ...                      # Additional views to be added
```

## Master Template: `fragments/layout.html`
**Path:** `classpath:/templates/fragments/layout.html`

### HTML Structure Components
| Component | th:fragment Identifier | Purpose |
|-----------|----------------------|---------|
| Page head (meta, imports) | N/A (static header) | CDNs for HTMX and Tailwind CSS 4 |
| Header / Navigation | `navigation` | Top navigation bar |
| **Primary Content** | `content(content)` | **Main fragment for dynamic content injection** |
| Footer | `footer` | Footer section |

### Fragment Usage Pattern
```html
<!-- Master layout includes the fragment tag -->
<main class="max-w-6xl mx-auto px-4 py-6"
     id="app-content"
     th:fragment="content(content)">
    <th:block th:replace="${content}"></th:block>
</main>
```

### HTMX Integration
- **Script:** `https://unpkg.com/htmx.org@1.9.10`
- **Purpose:** Enables asynchronous hypermedia interactions via `hx-*` attributes
- **Pattern:** HTMX requests return partial HTML fragments that swap into the `content` fragment

### Tailwind CSS Integration
- **Script:** `https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4`
- **Mode:** Utility-first CSS (v4 beta/alpha via CDN)
- **Purpose:** Rapid UI styling with mobile-responsive design system

## Template Resolution Map
| HTTP Path | Controller Method | View Name | Expected Behavior |
|-----------|-------------------|-----------|-------------------|
| `/` | `HomeController.index()` | `index.html` | Renders index view inside master layout's `content` fragment |
| `/auth/login` (GET) | `AuthenticationController.showLoginForm()` | `login.html` | Displays login form; redirects unauthenticated users from protected paths |
| `/auth/login` (POST) | `AuthenticationController.processLogin()` | `login.html` or redirect | Processes credentials; redirects to home on success, shows error otherwise |
| `/auth/logout` (GET) | `AuthenticationController.logout()` | redirect: `/` | Invalidates session and clears JSESSIONID cookie; redirects to home |
| `/auth/reset-password` (GET) | `AuthenticationController.showResetPasswordForm()` | `reset-password.html` | Displays password reset form for temp admin accounts only |
| `/auth/reset-password` (POST) | `AuthenticationController.processPasswordReset()` | `reset-password.html` or redirect | Processes new password; redirects to login on success, shows error otherwise |
| `/plant-top-plate/security/user-service` | Security bean registration | N/A | Registers `PlanTopPlateUserDetailsService` as Spring Security authentication service |
| `/plant-top-plate/security/password-encoder` | BCrypt encoder bean | N/A | Registers `BCryptPasswordEncoder` instance for password hashing/validation |

## Route Registration
The root path (`/`) resolves via:
```java
@GetMapping("/")
public String index() {
    return "index";  // Resolves to src/main/resources/templates/index.html
}
```

## Fragment Identifier Paths
| Path | Location | th:fragment ID | Access Pattern |
|------|----------|----------------|----------------|
| Master layout | `templates/fragments/layout.html` | N/A (root) | Thymeleaf includes via `<th:block>` |
| Navigation | `templates/fragments/layout.html` | `navigation` | Included in header block |
| **Main Content** | `templates/fragments/layout.html` | `content(content)` | **Primary HTMX render target** |
| Footer | `templates/fragments/layout.html` | `footer` | Included in footer block |

## Authentication Security Requirements

### Login Page (`/auth/login`, GET)
- **Access:** Public (HTTP 200, no authentication required)
- **Behavior:** Displays login form with username/password fields
- **Session Handling:** Creates new session on first POST; persists JSESSIONID cookie
- **Redirect Target:** Protected paths redirect unauthenticated users here via HTTP 302

### Logout (`/auth/logout`, GET)
- **Access:** Public (HTTP 200, no authentication required)
- **Behavior:** Invalidates session, clears JSESSIONID cookie
- **Redirect:** Always redirects to `/` (root) after logout

### Reset Password (`/auth/reset-password`, GET/POST)
- **GET Access:** Restricted to authenticated temp password users only
  - Redirects to home if user is not authenticated
  - Redirects to login if user has permanent password (not temp)
- **POST Access:** Same as GET + validates current password before update
- **Behavior:** Forces temporary admin accounts to set new password and clear temp flag
- **Redirect Success:** POST with valid credentials redirects to `/auth/login`
- **Redirect Interception:** POST to standard routes from temp password user redirects here instead

## Security Bean Registration Details

### PlanTopPlateUserDetailsService
- **Full Class Name:** `com.plantoplate.security.PlanToPlateUserDetailsService`
- **Purpose:** Loads `User` entities from database for Spring Security authentication
- **Bean Name:** `plantTopplateUserDetailsService` (configured in SecurityConfig)
- **Key Methods:**
  - `loadUserByUsername(String username)` - retrieves user by username, throws `UsernameNotFoundException` if not found
  - Returns `org.springframework.security.core.userdetails.User` populated from JPA entity

### TempPasswordInterceptor
- **Full Class Name:** `com.plantoplate.filter.TempPasswordInterceptor`
- **Purpose:** Intercepts authenticated requests where current user has temporary password
- **Filtering Strategy:**
  - Checks `currentUser.isTempPassword()` property after authentication
  - If TRUE: Redirects to `/auth/reset-password` for password reset flow
- **Integration:** Registered as Spring Security filter in SecurityConfig's `http.addFilterBefore(...)` chain

## HTMX Request Handling (Future)
When controller returns Thymeleaf views via `@GetMapping`/`@PostMapping`:
```java
@GetMapping("/endpoint")
public String endpoint() {
    return "view-name";  // e.g., "list", "create-form"
}
```

The view is rendered as a fragment and inserted into the master layout's `content` fragment via HTMX.

---
*Last updated: Task 2 - Authentication Infrastructure, Secure Session Management, & Temp Credentials Workflows [COMPLETE] / Test Suite Stabilization [COMPLETE]*
