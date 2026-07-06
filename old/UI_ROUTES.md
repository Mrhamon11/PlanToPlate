# PlanToPlate - UI Routes (Thymeleaf Templates)

## Default Layout Template: `layout.html`
**Location:** `src/main/resources/templates/layout.html`  
**Purpose:** Master layout containing `<html>`, `<head>`, and `<body>` structure with navigation, footer, and page injection point.

### Access Pattern
```thymeleaf
<html xmlns:th="http://www.thymeleaf.org"
      xmlns:sec="http://www.thymeleaf.org/extras/spring-security">
<head>...</head>
<body>
    <nav>...</nav>
    <main th:replace="@{::content}">...</main> <!-- Fragment injection -->
    <footer>...</footer>
</body>
</html>
```

### Thymeleaf Security Tags (`th:sec`)
| Tag | Purpose |
|------|----------|
| `<th:sec:authorize="hasRole('ADMIN')">...</th:sec:authorize>` | Render admin-only content |
| `<th:sec:authorize="isAuthenticated()">...</th:sec:authorize>` | Show logout link when logged in |

---

## Partial Fragments (Layout-Agnostic)

### Header Fragment: `fragments/header.html`
**Location:** `src/main/resources/templates/fragments/header.html`  
**Content:** Navigation bar, branding, login/logout user menu.

### Footer Fragment: `fragments/footer.html`
**Location:** `src/main/resources/templates/fragments/footer.html`  
**Content:** Copyright info, links to About, Help pages.

---

## Page-Specific Templates

### 1. Login Page
**Path:** `/auth/login`  
**Template:** `auth/login.html`  
**Controller:** `AuthenticationController.login()`  
**Layout:** Full layout (`layout.html`)  

```thymeleaf
<html xmlns:th="http://www.thymeleaf.org" th:replace="~{layout :: [content, ::loginForm]}">
  <div class="auth-form">
    <h2>Sign In</h2>
    <!-- Login form fields (username, password) -->
  </div>
</html>
```

---

### 2. Logout Confirmation
**Path:** `/auth/logout`  
**Template:** `auth/logout.html`  
**Controller:** `AuthenticationController.logout()`  
**Layout:** Full layout  

```thymeleaf
<html xmlns:th="http://www.thymeleaf.org" th:replace="~{layout :: [content, ::logoutConfirm]}">
  <div class="logout-confirmation">
    <h2>Logout</h2>
    <!-- Confirm logout action -->
  </div>
</html>
```

---

### 3. Home Page
**Path:** `/home`  
**Template:** `home.html`  
**Controller:** `HomeController.index()` (when authenticated)  
**Layout:** Full layout  

```thymeleaf
<html xmlns:th="http://www.thymeleaf.org" th:replace="~{layout :: [content, ::dashboard]}">
  <div class="dashboard">
    <!-- Welcome message, user info -->
  </div>
</html>
```

---

### 4. Register Page
**Path:** `/auth/register`  
**Template:** `auth/register.html`  
**Controller:** `AuthenticationController.register()`  
**Layout:** Full layout  

```thymeleaf
<html xmlns:th="http://www.thymeleaf.org" th:replace="~{layout :: [content, ::registerForm]}">
  <div class="auth-form">
    <h2>Create Account</h2>
    <!-- Registration form fields (username, password, role) -->
  </div>
</html>
```

---

### 5. Reset Password Page
**Path:** `/auth/reset-password`  
**Template:** `auth/reset-password.html`  
**Controller:** `AuthenticationController.resetPassword()`  
**Layout:** Full layout  

```thymeleaf
<html xmlns:th="http://www.thymeleaf.org" th:replace="~{layout :: [content, ::resetPasswordForm]}">
  <div class="auth-form">
    <h2>Reset Password</h2>
    <!-- Reset password form -->
  </div>
</html>
```

---

## Thymeleaf Fragment Composition

### Reusable UI Components

#### Login Form Component (`fragments/login-form.html`)
- Can be included in `auth/login.html` or embedded via layout injection.
- Handles username/password fields with CSRF token.

#### Logout Confirmation Component (`fragments/logout-confirm.html`)
- Used in `/auth/logout` to confirm logout action before session termination.

---

## Route Resolution Summary

| HTTP Path     | Template                    | Fragment Target       | Controller Method                |
|---------------|-----------------------------|-----------------------|----------------------------------|
| `/auth/login` | `auth/login.html`           | `::loginForm`         | `AuthenticationController.login()` |
| `/auth/logout`| `auth/logout.html`          | `::logoutConfirm`     | `AuthenticationController.logout()` |
| `/home`       | `home.html`                 | `::dashboard`         | `HomeController.index()`         |
| `/auth/register`| `auth/register.html`      | `::registerForm`      | `AuthenticationController.register()` |
| `/auth/reset-password`| `auth/reset-password.html`| `::resetPasswordForm` | `AuthenticationController.resetPassword()` |

---

*Last updated: Task 3 - Authentication Routes & Thymeleaf Layouts [COMPLETE]*
