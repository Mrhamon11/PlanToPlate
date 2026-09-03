"""Recipes — the central model of the application (``Plan/05-Recipes/design.md``).

A ``Recipe`` is a list of components (each an ingredient *or* a sub-recipe, never both) plus a
mandatory yield. The yield is what lets a sub-recipe be scaled: "1 cup of marinara" is only
meaningful once the marinara recipe declares it makes 4 cups (MILESTONES.md C1). Per-user
rating / favourite / times-made live on a separate ``RecipeStats`` row, never on the shared
recipe (D3 / C4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from catalog.models import Ingredient, Tag, Unit
from core.models import OwnedModel
from recipes.managers import RecipeManager

if TYPE_CHECKING:
    from core.services.copying import Copier


def validate_positive_yield(value: object) -> None:
    """A recipe's yield must be greater than zero — it is the divisor in step 3 of the flatten
    algorithm (design.md, "Edge cases": "Yield of zero: rejected. It is a division by zero").
    """
    if value is not None and value <= 0:
        raise ValidationError(
            "A recipe's yield must be greater than zero.",
            code="non_positive_yield",
        )


def _existing_copy_for(node: OwnedModel, actor) -> OwnedModel | None:
    """The copy of ``node`` that ``actor`` already owns, if any — so a second copy operation
    reuses it instead of trying (and, for ``Ingredient``, failing) to create a duplicate.

    Matched first on lineage (``copied_from``); then, for ``Ingredient`` only, on name.
    ``catalog`` enforces one ingredient per ``(owner, name)``, so if the actor already owns a
    same-named ingredient — one they copied earlier from a *different* origin, or made by hand
    — a second copy literally cannot be stored and reusing theirs is the only non-erroring
    outcome. ``Recipe`` has no such constraint, so a same-named recipe from another origin is
    left to copy normally rather than silently collapsed into an unrelated one.
    """
    manager = type(node)._default_manager
    by_lineage = manager.filter(copied_from=node, owner=actor).order_by("pk").first()
    if by_lineage is not None:
        return by_lineage
    if isinstance(node, Ingredient):
        return manager.filter(owner=actor, name__iexact=node.name).order_by("pk").first()
    return None


def _copy_or_reference(node: OwnedModel, copier: Copier) -> OwnedModel:
    """Resolve what a copied component should point at for its ingredient / sub-recipe.

    - A *system* node is shared vocabulary — return it unchanged.
    - A node ``copier.actor`` has *already copied* (in an earlier operation, or earlier in this
      one) is reused rather than copied again. Without this, copying two recipes that share a
      private ingredient — or re-copying a recipe — hits the ``(owner, name)`` uniqueness
      constraint on ``Ingredient`` and raises ``IntegrityError``; reuse also keeps a user's
      catalog free of "Baharat", "Baharat (2)", … duplicates (task 05 dev-test finding).
    - Anything else is deep-copied so the copy owns its whole tree (see ``Recipe.copy_children``).
    """
    if node.is_system:
        return node
    existing = _existing_copy_for(node, copier.actor)
    if existing is not None:
        return existing
    return copier.copy(node)


class RecipeRole(models.TextChoices):
    PROTEIN = "PROTEIN", "Protein"
    CARB = "CARB", "Carb"
    VEGETABLE = "VEGETABLE", "Vegetable"
    ONE_POT = "ONE_POT", "One-pot"
    SAUCE = "SAUCE", "Sauce"
    DESSERT = "DESSERT", "Dessert"
    SIDE = "SIDE", "Side"
    BREAKFAST = "BREAKFAST", "Breakfast"
    OTHER = "OTHER", "Other"


class Recipe(OwnedModel):
    """A recipe of ingredients and sub-recipes, with a yield, instructions, and times.

    ``role`` is stored explicitly rather than derived from ingredients: the meal planner needs
    to tell a Protein from a Carb, and derivation fails on exactly the interesting cases — a
    chicken *stock* is not a protein dish (design.md, "``role`` is explicit" / C7).
    """

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    instructions = models.TextField()
    yield_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[validate_positive_yield],
    )
    yield_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="recipe_yields")
    prep_minutes = models.PositiveIntegerField(default=0)
    cook_minutes = models.PositiveIntegerField(default=0)
    role = models.CharField(
        max_length=16,
        choices=RecipeRole.choices,
        default=RecipeRole.OTHER,
        db_index=True,
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="recipes")
    source_url = models.URLField(blank=True)

    objects = RecipeManager()

    class Meta(OwnedModel.Meta):
        ordering = ["name"]
        constraints = [
            *OwnedModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(yield_quantity__gt=0),
                name="recipes_recipe_yield_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return reverse("recipes:recipe-detail", args=[self.pk])

    def _component_dependencies(self) -> list[OwnedModel]:
        deps: list[OwnedModel] = []
        for component in self.components.all():
            if component.ingredient_id:
                deps.append(component.ingredient)
            if component.sub_recipe_id:
                deps.append(component.sub_recipe)
        return deps

    def share_dependencies(self) -> list[OwnedModel]:
        """Every ingredient and sub-recipe this recipe references — read-access to all of them
        must cascade when the recipe is shared (design.md, "Security notes"; core/README.md
        step 2).
        """
        return self._component_dependencies()

    def copy_children(self, new_obj: Recipe, *, copier: Copier) -> None:
        """Deep-copy every component onto ``new_obj``.

        A *private* ingredient or sub-recipe is itself copied (via ``copier.copy`` so the cycle
        guard and depth cap apply), never merely re-pointed at the original owner's row (C6).

        A *system* ingredient or sub-recipe is passed through **by reference**: it is
        immutable, nobody-owned, and globally readable, so the "no pointers into someone else's
        data" rule does not apply to it. Forking the seeded catalog into a private duplicate per
        copied recipe would fill the ingredient typeahead with duplicates and break cross-recipe
        shopping-list aggregation, which groups by ``ingredient.pk`` (task 05 review finding 1).
        """
        for component in self.components.all():
            new_ingredient = (
                _copy_or_reference(component.ingredient, copier)
                if component.ingredient_id
                else None
            )
            new_sub_recipe = (
                _copy_or_reference(component.sub_recipe, copier)
                if component.sub_recipe_id
                else None
            )
            RecipeComponent.objects.create(
                recipe=new_obj,
                ingredient=new_ingredient,
                sub_recipe=new_sub_recipe,
                quantity=component.quantity,
                unit=component.unit,
                position=component.position,
                note=component.note,
            )


class RecipeComponent(models.Model):
    """One line of a recipe: an ingredient *or* a sub-recipe (never both, never neither —
    enforced by a database ``CheckConstraint``), with a quantity and unit.

    ``PROTECT`` on both foreign keys: deleting an ingredient or a recipe that something else
    depends on must fail loudly with a 409 naming the dependents, not silently gut a recipe
    (design.md, "Components").
    """

    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="components")
    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="used_in_components",
    )
    sub_recipe = models.ForeignKey(
        Recipe,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="used_in",
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="recipe_components")
    position = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(ingredient__isnull=False) & models.Q(sub_recipe__isnull=True))
                | (models.Q(ingredient__isnull=True) & models.Q(sub_recipe__isnull=False)),
                name="recipes_component_ingredient_xor_subrecipe",
            )
        ]

    def __str__(self) -> str:
        target = self.ingredient or self.sub_recipe
        return f"{self.quantity} {self.unit} {target}"


class RecipeStats(models.Model):
    """Per-user rating / favourite / times-made for one recipe (D3 / C4).

    Rows are created lazily — most users never rate most recipes — so access goes through
    ``recipes.services.stats``, not direct instantiation. ``last_made_at`` is what the meal
    planner's ``no_repeat_days`` gear reads.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recipe_stats",
    )
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="stats")
    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    is_favorite = models.BooleanField(default=False)
    times_made = models.PositiveIntegerField(default=0)
    last_made_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "recipe"],
                name="recipes_recipestats_unique_user_recipe",
            ),
            models.CheckConstraint(
                condition=models.Q(rating__isnull=True) | models.Q(rating__gte=1, rating__lte=5),
                name="recipes_recipestats_rating_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.recipe}"
