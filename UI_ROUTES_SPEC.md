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
*Last updated: Task 1 - Project Skeleton & Layout Setup [COMPLETE]*
