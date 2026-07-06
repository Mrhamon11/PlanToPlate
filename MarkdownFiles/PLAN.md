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

---

## Domain-Based App Architecture (Recommended Structure)

### Project Directory Layout

```
plan_to_plate/
├── coremodels/          # Base classes, mixins, utilities ONLY
│   ├── __init__.py
│   ├── models.py        # BaseModel mixin with _filter_for_user()
│   └── permissions.py   # PermissionQuerySet helpers (shared logic)
│
├── users/               # CustomUser + Permission model
│   ├── __init__.py
│   ├── models.py        # CustomUser, Permission (first owner of this model)
│   ├── admin.py         # User/Permission admin registration
│   ├── views.py         # Auth views, user management
│   └── serializers.py   # DRF auth serializers
│
├── ingredients/         # Ingredient domain
│   ├── __init__.py
│   ├── models.py        # Ingredient app-specific models only
│   ├── admin.py
│   ├── urls.py          # Internal API: /internal/ingredients/
│   ├── views.py         # Internal views (fast ORM access)
│   └── serializers.py   # DRF serializers with permission filters
│
├── recipes/             # Recipe domain
│   ├── __init__.py
│   ├── models.py        # Recipe, RecipeIngredient, CookingInstruction
│   ├── admin.py
│   ├── urls.py          # Internal API: /internal/recipes/
│   ├── views.py         # Internal views
│   └── serializers.py   # DRF serializers (nested ingredient support)
│
├── recipebooks/         # RecipeBook domain
│   ├── __init__.py
│   ├── models.py        # RecipeBook, BookCategory
│   ├── admin.py
│   ├── urls.py          # Internal API: /internal/recipebooks/
│   ├── views.py         # Internal views
│   └── serializers.py   # DRF serializers
│
├── dishes/              # Dish domain
│   ├── __init__.py
│   ├── models.py        # Dish, DishIngredient, MealType
│   ├── admin.py
│   ├── urls.py          # Internal API: /internal/dishes/
│   ├── views.py         # Internal views (meal planner logic)
│   └── serializers.py   # DRF serializers
│
├── lists/               # List domain
│   ├── __init__.py
│   ├── models.py        # List, ListItem
│   ├── admin.py
│   ├── urls.py          # Internal API: /internal/lists/
│   ├── views.py         # Internal views (meal planner endpoint)
│   └── serializers.py   # DRF serializers
│
└── api/                 # External API layer
    ├── __init__.py
    ├── routers.py       # DRF ViewSetRouter aggregator
    └── urls.py          # Versioned: /api/v1/
```

---

## Key Architectural Decisions

### 1. Shared Permission Model in `users` App

```python
# users/models.py
class Permission(models.Model):
    """Cross-cutting permission model lives in the auth app"""
    object_type = models.CharField(
        max_length=50, 
        choices=('ingredient', 'recipe', 'dish', 'list', 'recipebook')
    )
    object_id = models.BigIntegerField()  # PK of target object
    owner = models.ForeignKey('users.CustomUser', on_delete=models.CASCADE)
    granted_to = models.ForeignKey('users.CustomUser', on_delete=models.CASCADE, 
                                   blank=True, null=True)  # For sharing
    read_only = models.BooleanField(default=True)
```

Each domain app can import and use this permission model:
```python
# ingredients/models.py
class Ingredient(models.Model):
    name = models.CharField(max_length=200)
    
    def _filter_for_user(self, user):
        from coremodels.permissions import PermissionQuerySet
        return PermissionQuerySet(self.objects.all()).for_user(user)
```

### 2. Internal vs External API Pattern

Each domain app serves two purposes:

| Purpose | Location | Authentication | ORM Style |
|---------|----------|----------------|-----------|
| **Internal Views** | `domain/urls.py` → `/internal/` | Optional | Direct model access, no filtering |
| **External API** | `api/routers.py` → `/api/v1/` | Required | Filtered by Permission model |

```python
# recipes/views.py (internal) - Fast, raw data
def get_recipe_data(request, pk):
    recipe = Recipe.objects.get(pk=pk)  # No permission check!
    return Response(recipe.serialize())  # Raw dict for internal use

# recipes/serializers.py (external) - Permission-aware
class RecipeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recipe
        fields = '__all__'
    
    def get_queryset(self):
        user = self.context['user']
        return self.Meta.model.objects.filter(
            owner=user  # Or grant_to=user
        )
```

### 3. Base Model Mixin in `coremodels`

```python
# coremodels/models.py
class BaseModel(models.Model):
    rating = models.FloatField()  # Shared across all models
    favorite = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    
    _created_by = models.ForeignKey('users.CustomUser', on_delete=models.SET_NULL, 
                                    null=True, blank=True)  # User ownership
    
    class Meta:
        abstract = True
    
    def _filter_for_user(self, queryset, user):
        """Shared filtering logic"""
        return queryset.filter(owner=user) | Permission.objects.filter(
            object_type=self.__class__.__name__.lower(),
            object_id=self.pk,
            granted_to=user
        )
```

### 4. Admin Registration in Each App

```python
# ingredients/admin.py (domain-specific admin)
from django.contrib import admin
from .models import Ingredient

@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit', '_created_by')
```

No need for a mega-admin app—each domain manages its own objects.

---

## How Apps Interact

### Import Models Directly (Same Process, No HTTP!)

```python
# users/views.py - User management
from django.contrib.auth.models import User  # Django's built-in
from .models import CustomUser, Permission

class UserView:
    def create(self, request):
        user = CustomUser.objects.create(
            username=request.data['username']
        )
        return Response(user.serialize())
```

```python
# api/routers.py - Aggregates all external API routes
from rest_framework.routers import DefaultRouter
from ingredients.views import IngredientViewSet
from recipes.views import RecipeViewSet

router = DefaultRouter()
router.register('ingredients', IngredientViewSet)
router.register('recipes', RecipeViewSet)
```

---

## URL Structure Example

```python
# urls.py (main project)
urlpatterns = [
    # Public API with permission checks
    path('api/v1/', include([
        path('auth/', include('users.urls')),  # Login/logout/user-mgmt
        path('ingredients/', IngredientViewSet.as_view(), name='ingredient'),
        path('recipes/', RecipeViewSet.as_view(), name='recipe'),
        path('dishes/', DishViewSet.as_view(), name='dish'),
        path('lists/', ListViewSet.as_view(), name='list'),
    ])),
    
    # Internal API for Django Views (no auth needed)
    path('internal/', include([
        path('ingredients/', IngredientView.as_view()),  # Fast, no filtering
        path('recipes/', RecipeView.as_view()),
        path('dishes/', DishView.as_view()),
    ])),
    
    # Admin panel (Django admin URL is /admin/)
]
```

---

## Benefits of Domain-Based Separation

| Aspect | Single `coremodels` App | Domain-Based Apps |
|--------|-------------------------|-------------------|
| **Testing** | Hard to isolate tests per feature | Easy: test ingredients independently |
| **Migrations** | One big migration file | Small, focused migrations per app |
| **Scalability** | All models in one place → hard to manage | Add new domains without touching others |
| **Team Collaboration** | Code changes ripple everywhere | Work on separate features in parallel |
| **Django Admin** | Flat permission hierarchy | Natural grouping by domain |

---

## When You Might Consolidate Models

Only consider consolidating models if:

- You have >10 apps and want to simplify model definitions
- Multiple teams own the same feature (models are a shared contract)
- You're building an internal admin that must see all objects in one place

**Otherwise, stick with domain-based separation—it's the Django way.**

---