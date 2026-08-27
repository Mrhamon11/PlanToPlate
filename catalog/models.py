"""Units, tags, and ingredients — the measurement system and the vocabulary every recipe is
written in (``Plan/04-Units-And-Ingredients/design.md``).

``Unit`` and ``Tag`` are shared vocabulary, not owned: letting each user define a private "cup"
would make shared recipes unreadable. ``Ingredient`` is an ``OwnedModel`` — cross-user
duplication ("Chicken Breast" owned by fifteen people) is allowed and expected, but one user
owning two rows with the same name is not.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils.text import slugify

from core.models import OwnedModel


class Dimension(models.TextChoices):
    MASS = "MASS", "Mass"
    VOLUME = "VOLUME", "Volume"
    COUNT = "COUNT", "Count"


#: The one COUNT family whose members carry a real numeric ratio to one another: ``each`` (1),
#: ``half dozen`` (6), ``dozen`` (12). Every other counted unit (can, slice, clove, …) is a
#: singleton — it converts only to itself, because "1 can" and "2 slices" have no fixed ratio.
#:
#: This is the canonical value ``catalog/fixtures/units.json`` writes for those three rows and
#: the D34 conversion contract is defined against; ``Unit.is_generic_count`` and the seed tests
#: read it back so a fixture drift ("generics" / "count") is caught rather than silently
#: producing three mutually-inconvertible singletons.
GENERIC_COUNT_FAMILY = "generic"


def validate_positive_factor(value: Decimal | None) -> None:
    """A unit's factor to its base must be greater than zero — it is a multiplier and a
    divisor in the conversion service, so zero or negative is nonsensical and a zero divides
    by zero. Mirrors ``validate_positive_density`` on ``Ingredient``.
    """
    if value is not None and value <= 0:
        raise ValidationError(
            "A unit's factor to its base unit must be greater than zero.",
            code="non_positive_factor",
        )


class Unit(models.Model):
    """A single unit of measure and its factor to its dimension's base unit.

    Base units are gram (MASS), millilitre (VOLUME), and each (COUNT), all with
    ``to_base_factor == 1``. Storing one factor per unit means conversion within a dimension is
    a single multiply-and-divide with no conversion table to maintain (design.md, "Units").
    """

    name = models.CharField(max_length=40, unique=True)
    plural = models.CharField(max_length=40, blank=True)
    #: Unique: ``seed_catalog`` builds its fixture lookup keyed on ``abbrev`` as well as ``name``
    #: (so ``{"unit": "ea"}`` in ``ingredients.json`` resolves), and the app-wide unit picker
    #: shows the abbreviation as the human label — two units sharing one would make both
    #: ambiguous. Units are admin-managed, so this is a guard rail, not a user-facing flow.
    abbrev = models.CharField(max_length=12, unique=True)
    dimension = models.CharField(max_length=6, choices=Dimension.choices, db_index=True)
    to_base_factor = models.DecimalField(
        max_digits=20, decimal_places=10, validators=[validate_positive_factor]
    )
    #: COUNT units only. Units sharing a non-empty ``count_family`` interconvert on their
    #: ``to_base_factor`` ratio; units in different families (or with no family) never do.
    #: ``each``/``dozen``/``half dozen`` share ``GENERIC_COUNT_FAMILY``; every packaging or piece
    #: unit is its own singleton family so ``convert(2, clove, can)`` refuses instead of
    #: returning ``2`` (MILESTONES.md decision D34). Empty for MASS and VOLUME, where the
    #: dimension alone settles interconvertibility.
    count_family = models.CharField(max_length=20, blank=True, default="")
    is_system = models.BooleanField(default=True)

    class Meta:
        ordering = ["dimension", "to_base_factor"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(to_base_factor__gt=0),
                name="catalog_unit_to_base_factor_positive",
            )
        ]

    def __str__(self) -> str:
        return self.abbrev

    @property
    def is_generic_count(self) -> bool:
        """``each`` / ``dozen`` / ``half dozen`` — the one COUNT family whose members carry a
        real ratio to one another (``GENERIC_COUNT_FAMILY``, D34). Every other counted unit is
        its own singleton and returns ``False`` here, as does every MASS/VOLUME unit.
        """
        return self.count_family == GENERIC_COUNT_FAMILY

    def label_for(self, quantity: Decimal | int | None) -> str:
        """The singular or plural name to show next to ``quantity`` ("cup" vs "cups").

        Plural only above one — kitchen convention writes "¼ cup" and "1 cup", "2 cups".
        """
        if quantity is not None and Decimal(quantity) > 1:
            return self.plural or f"{self.name}s"
        return self.name


class TagKind(models.TextChoices):
    CUISINE = "CUISINE", "Cuisine"
    PROTEIN = "PROTEIN", "Protein"
    DIET = "DIET", "Diet"
    FREEFORM = "FREEFORM", "Freeform"


class Tag(models.Model):
    """A label for recipes and ingredients. ``kind`` matters because the meal planner's tag
    limits (MILESTONES.md section 5, gear 4) operate mainly on ``PROTEIN`` tags and the UI
    groups the picker by kind.
    """

    name = models.CharField(max_length=40, unique=True)
    kind = models.CharField(max_length=8, choices=TagKind.choices, default=TagKind.FREEFORM)
    slug = models.SlugField(max_length=50, unique=True, blank=True)

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


def validate_positive_density(value: Decimal | None) -> None:
    """A density of zero or below is rejected: zero divides by zero in the conversion service,
    and a negative density is meaningless (design.md, "Edge cases").
    """
    if value is not None and value <= 0:
        raise ValidationError(
            "Density must be greater than zero — leave it blank if the density is unknown.",
            code="non_positive_density",
        )


class Ingredient(OwnedModel):
    """A single ingredient in the catalog.

    ``density_g_per_ml`` is null by default, and null means "refuse to convert between mass and
    volume for this ingredient" rather than "assume 1.0" — a fabricated density produces a
    confidently wrong shopping list (design.md, "Ingredient").
    """

    #: Declared explicitly per ``core/README.md`` ("Does this model contain other owned
    #: objects?") and MILESTONES.md decision D33: an ingredient has no owned children. Once task
    #: 05 adds ``RecipeComponent`` (whose ``.recipe`` FK points at ``Recipe`` and ``.ingredient``
    #: FK points here), ``test_conventions.py``'s hooks-guard relation-walk can no longer tell
    #: this leaf apart from that container, so it needs this deliberate opt-out rather than a
    #: no-op ``share_dependencies()``/``copy_children()`` override.
    contains_owned_children = False

    name = models.CharField(max_length=120)
    default_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="ingredients")
    density_g_per_ml = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[validate_positive_density],
    )
    is_staple = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, blank=True, related_name="ingredients")

    class Meta(OwnedModel.Meta):
        ordering = ["name"]
        constraints = [
            *OwnedModel.Meta.constraints,
            # Case-insensitive uniqueness, expressed as functional unique constraints so they
            # hold on Postgres too, not just SQLite. One user cannot own two "Chicken Breast"
            # rows; the system catalog cannot hold two either. The two are separate partial
            # constraints because a user row and a system row with the same name must coexist.
            models.UniqueConstraint(
                Lower("name"),
                "owner",
                name="catalog_ingredient_unique_owner_name_ci",
                condition=models.Q(owner__isnull=False),
            ),
            models.UniqueConstraint(
                Lower("name"),
                name="catalog_ingredient_unique_system_name_ci",
                condition=models.Q(is_system=True),
            ),
            models.CheckConstraint(
                condition=models.Q(density_g_per_ml__isnull=True)
                | models.Q(density_g_per_ml__gt=0),
                name="catalog_ingredient_density_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:ingredient-detail", kwargs={"pk": self.pk})

    def clean(self) -> None:
        super().clean()
        if self.name:
            self.name = self.name.strip()

    def save(self, *args, **kwargs) -> None:
        if self.name:
            self.name = self.name.strip()
        super().save(*args, **kwargs)
