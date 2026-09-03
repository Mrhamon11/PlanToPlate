"""Flatten / aggregate tests — the correctness core (``Plan/05-Recipes/test-plan.md``,
"Flatten"). Expected values are hand-computed in each test.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from recipes.services.flatten import FlatLine, aggregate, flatten
from recipes.services.graph import CycleError, DepthExceededError

pytestmark = pytest.mark.django_db


def _line_for(lines, ingredient_name):
    matches = [line for line in lines if line.ingredient.name == ingredient_name]
    assert len(matches) == 1, f"expected exactly one {ingredient_name} line, got {matches}"
    return matches[0]


def test_flatten_simple_recipe(make_recipe, make_ingredient, gram, add_ingredient):
    recipe = make_recipe(name="Salsa")
    add_ingredient(recipe, make_ingredient("Tomato"), 800, gram, position=0)
    add_ingredient(recipe, make_ingredient("Onion"), 150, gram, position=1)

    lines = flatten(recipe)

    assert {line.ingredient.name: line.quantity for line in lines} == {
        "Tomato": Decimal("800"),
        "Onion": Decimal("150"),
    }
    assert all(line.from_recipes == ("Salsa",) for line in lines)
    assert all(line.unit == gram for line in lines)


def test_flatten_scales_by_factor(make_recipe, make_ingredient, gram, add_ingredient):
    recipe = make_recipe(name="Salsa")
    add_ingredient(recipe, make_ingredient("Tomato"), 800, gram, position=0)
    add_ingredient(recipe, make_ingredient("Onion"), 150, gram, position=1)

    lines = flatten(recipe, factor=Decimal("2"))

    assert _line_for(lines, "Tomato").quantity == Decimal("1600")
    assert _line_for(lines, "Onion").quantity == Decimal("300")


def test_flatten_rejects_float_factor(make_recipe, make_ingredient, gram, add_ingredient):
    """Task 05 review NB2: a ``float`` factor is refused before it can carry binary rounding
    error into the flattened quantities (mirrors ``catalog.services.units._as_decimal``).
    """
    recipe = make_recipe(name="Salsa")
    add_ingredient(recipe, make_ingredient("Tomato"), 800, gram, position=0)

    with pytest.raises(TypeError):
        flatten(recipe, factor=2.0)


@pytest.fixture
def marinara(make_recipe, make_ingredient, gram, add_ingredient, units):
    recipe = make_recipe(name="Marinara", yield_quantity=Decimal("4.000"), yield_unit=units["cup"])
    add_ingredient(recipe, make_ingredient("Crushed Tomatoes"), 800, gram, position=0)
    add_ingredient(recipe, make_ingredient("Garlic"), 4, units["clove"], position=1)
    add_ingredient(
        recipe,
        make_ingredient("Olive Oil", is_staple=True),
        2,
        units["tablespoon"],
        position=2,
    )
    return recipe


def test_flatten_sub_recipe_scaled_by_yield(
    marinara, make_recipe, make_ingredient, gram, units, add_ingredient, add_sub_recipe
):
    parm = make_recipe(name="Chicken Parm")
    add_ingredient(parm, make_ingredient("Chicken"), 500, gram, position=0)
    add_sub_recipe(parm, marinara, 1, units["cup"], position=1)

    lines = flatten(parm)

    # Marinara yields 4 cups; Chicken Parm uses 1 cup -> a quarter of every marinara line.
    assert _line_for(lines, "Chicken").quantity == Decimal("500")
    assert _line_for(lines, "Crushed Tomatoes").quantity == Decimal("200")
    assert _line_for(lines, "Garlic").quantity == Decimal("1")
    assert _line_for(lines, "Olive Oil").quantity == Decimal("0.5")
    assert _line_for(lines, "Crushed Tomatoes").from_recipes == ("Chicken Parm", "Marinara")


def test_flatten_sub_recipe_unit_converted(
    make_recipe, make_ingredient, gram, units, add_ingredient, add_sub_recipe
):
    sub = make_recipe(name="Stock", yield_quantity=Decimal("4.000"), yield_unit=units["tablespoon"])
    add_ingredient(sub, make_ingredient("Bones"), 800, gram)

    parent = make_recipe(name="Soup")
    # 6 tsp == exactly 2 tbsp; sub yields 4 tbsp -> factor 0.5. The tsp -> tbsp conversion
    # must happen before the yield division.
    add_sub_recipe(parent, sub, 6, units["teaspoon"])

    lines = flatten(parent)

    assert _line_for(lines, "Bones").quantity == Decimal("400")


def test_flatten_nested_two_levels(
    make_recipe, make_ingredient, gram, units, add_ingredient, add_sub_recipe
):
    c = make_recipe(name="C", yield_quantity=Decimal("4.000"), yield_unit=units["cup"])
    add_ingredient(c, make_ingredient("Flour"), 800, gram)

    b = make_recipe(name="B", yield_quantity=Decimal("2.000"), yield_unit=units["cup"])
    add_sub_recipe(b, c, 1, units["cup"])

    a = make_recipe(name="A")
    add_sub_recipe(a, b, 1, units["cup"])

    lines = flatten(a)

    # factor = 1 * (1/2) * (1/4) = 0.125 ; 800 * 0.125 = 100
    assert _line_for(lines, "Flour").quantity == Decimal("100")


def test_flatten_respects_depth_limit(make_recipe, make_ingredient, gram, cup, add_sub_recipe):
    recipes = [make_recipe(name=f"r{i}") for i in range(7)]  # 6 sub-recipe edges
    for parent, child in zip(recipes, recipes[1:], strict=False):
        add_sub_recipe(parent, child, 1, cup)

    with pytest.raises(DepthExceededError):
        flatten(recipes[0])

    # A five-edge chain is within the limit.
    shallow = [make_recipe(name=f"s{i}") for i in range(6)]
    for parent, child in zip(shallow, shallow[1:], strict=False):
        add_sub_recipe(parent, child, 1, cup)
    assert flatten(shallow[0]) == []


def test_flatten_terminates_on_cycle(make_recipe, cup, add_sub_recipe):
    a = make_recipe(name="A")
    b = make_recipe(name="B")
    add_sub_recipe(a, b, 1, cup)
    add_sub_recipe(b, a, 1, cup)  # bypasses the guard

    with pytest.raises(CycleError):
        flatten(a)


def test_flatten_records_provenance(
    marinara, make_recipe, make_ingredient, gram, units, add_ingredient, add_sub_recipe
):
    parm = make_recipe(name="Chicken Parm")
    add_sub_recipe(parm, marinara, 1, units["cup"])

    line = _line_for(flatten(parm), "Crushed Tomatoes")

    assert "Marinara" in line.from_recipes
    assert "Chicken Parm" in line.from_recipes


def test_aggregate_sums_same_ingredient_same_dimension(
    make_recipe, make_ingredient, units, add_ingredient
):
    from catalog.services.units import convert

    flour = make_ingredient("Flour")
    recipe = make_recipe(name="Bread")
    add_ingredient(recipe, flour, 200, units["gram"], position=0)
    add_ingredient(recipe, flour, 1, units["pound"], position=1)

    result = aggregate(flatten(recipe))

    assert len(result) == 1
    assert convert(result[0].quantity, result[0].unit, units["gram"]) == Decimal("653.59237")


def test_aggregate_keeps_incompatible_dimensions_separate(
    make_recipe, make_ingredient, units, add_ingredient
):
    flour = make_ingredient("Flour")  # no density
    recipe = make_recipe(name="Bread")
    add_ingredient(recipe, flour, 200, units["gram"], position=0)
    add_ingredient(recipe, flour, 2, units["cup"], position=1)

    result = aggregate(flatten(recipe))

    assert len(result) == 2


def test_aggregate_keeps_incompatible_count_families_separate(
    make_recipe, make_ingredient, units, add_ingredient
):
    # D34: two counted units with no shared family have no fixed ratio — an ``IncompatibleUnits``
    # aggregation must handle exactly like a missing density: keep the lines separate.
    garlic = make_ingredient("Garlic")
    recipe = make_recipe(name="Aioli")
    add_ingredient(recipe, garlic, 3, units["clove"], position=0)
    add_ingredient(recipe, garlic, 1, units["can"], position=1)

    result = aggregate(flatten(recipe))

    assert len(result) == 2


def test_aggregate_uses_density_when_available(make_recipe, make_ingredient, units, add_ingredient):
    flour = make_ingredient("Flour", density_g_per_ml=Decimal("0.6"))
    recipe = make_recipe(name="Bread")
    add_ingredient(recipe, flour, 200, units["gram"], position=0)
    add_ingredient(recipe, flour, 2, units["cup"], position=1)

    result = aggregate(flatten(recipe))

    assert len(result) == 1
    # 2 cups = 473.176473 ml * 0.6 = 283.905884 g ; + 200 g = 483.905884 g
    assert result[0].unit == units["gram"]
    assert abs(result[0].quantity - Decimal("483.905884")) < Decimal("0.001")


def test_aggregate_converts_to_friendly_unit(make_recipe, make_ingredient, units, add_ingredient):
    flour = make_ingredient("Flour")
    recipe = make_recipe(name="Bread")
    add_ingredient(recipe, flour, 1500, units["gram"])

    result = aggregate(flatten(recipe))

    assert len(result) == 1
    assert result[0].unit == units["kilogram"]
    assert result[0].quantity == Decimal("1.5")


def test_aggregate_demotes_to_smaller_metric_unit(
    make_recipe, make_ingredient, units, add_ingredient
):
    # Bucket unit is kilograms (first line); the total lands below 1, so it must demote down
    # the metric ladder to grams — not across to pounds (task 05 review finding 2).
    flour = make_ingredient("Flour")
    recipe = make_recipe(name="Bread")
    add_ingredient(recipe, flour, Decimal("0.15"), units["kilogram"], position=0)
    add_ingredient(recipe, flour, Decimal("0.15"), units["kilogram"], position=1)

    (line,) = aggregate(flatten(recipe))

    assert line.unit.name == "gram"
    assert line.quantity == Decimal("300")


def test_aggregate_metric_volume_stays_metric(make_recipe, make_ingredient, units, add_ingredient):
    # 0.3 litre must render as 300 ml, never "1.27 cup" — _friendly_unit may not promote or
    # demote across measurement systems (task 05 review finding 2).
    milk = make_ingredient("Milk")
    recipe = make_recipe(name="Custard")
    add_ingredient(recipe, milk, Decimal("0.15"), units["litre"], position=0)
    add_ingredient(recipe, milk, Decimal("0.15"), units["litre"], position=1)

    (line,) = aggregate(flatten(recipe))

    assert line.unit.name == "millilitre"
    assert line.quantity == Decimal("300")


def test_aggregate_promotes_volume_within_metric(
    make_recipe, make_ingredient, units, add_ingredient
):
    water = make_ingredient("Water")
    recipe = make_recipe(name="Stock")
    add_ingredient(recipe, water, 1500, units["millilitre"])

    (line,) = aggregate(flatten(recipe))

    assert line.unit.name == "litre"
    assert line.quantity == Decimal("1.5")


def test_aggregate_keeps_unit_when_no_metric_ladder_neighbour(
    make_recipe, make_ingredient, units, add_ingredient
):
    # A pound total below 1 has no power-of-ten neighbour among the seeded units, so rather
    # than cross into grams _friendly_unit keeps pounds (task 05 review finding 2: "keep the
    # source unit unless a strictly better same-system unit exists").
    butter = make_ingredient("Butter")
    recipe = make_recipe(name="Shortbread")
    add_ingredient(recipe, butter, Decimal("0.5"), units["pound"])

    (line,) = aggregate(flatten(recipe))

    assert line.unit.name == "pound"
    assert line.quantity == Decimal("0.5")


def test_exclude_staples(make_recipe, make_ingredient, gram, add_ingredient):
    recipe = make_recipe(name="Bread")
    add_ingredient(recipe, make_ingredient("Flour"), 200, gram, position=0)
    add_ingredient(recipe, make_ingredient("Salt", is_staple=True), 5, gram, position=1)
    add_ingredient(recipe, make_ingredient("Oil", is_staple=True), 10, gram, position=2)

    assert len(flatten(recipe)) == 3
    kept = flatten(recipe, exclude_staples=True)
    assert [line.ingredient.name for line in kept] == ["Flour"]


def test_flatten_returns_decimals(
    make_recipe, make_ingredient, gram, units, add_ingredient, add_sub_recipe
):
    sub = make_recipe(name="Sauce", yield_quantity=Decimal("4.000"), yield_unit=units["cup"])
    add_ingredient(sub, make_ingredient("Tomato"), 800, gram)
    parent = make_recipe(name="Pasta")
    add_ingredient(parent, make_ingredient("Pasta"), 500, gram, position=0)
    add_sub_recipe(parent, sub, 1, units["cup"], position=1)

    for line in flatten(parent):
        assert isinstance(line.quantity, Decimal)


def test_flatten_query_count(
    make_recipe,
    make_ingredient,
    gram,
    units,
    add_ingredient,
    add_sub_recipe,
    django_assert_max_num_queries,
):
    level3 = make_recipe(name="L3", yield_quantity=Decimal("4.000"), yield_unit=units["cup"])
    for i in range(18):
        add_ingredient(level3, make_ingredient(f"i3-{i}"), 10, gram, position=i)

    level2 = make_recipe(name="L2", yield_quantity=Decimal("4.000"), yield_unit=units["cup"])
    add_ingredient(level2, make_ingredient("i2"), 10, gram, position=0)
    add_sub_recipe(level2, level3, 1, units["cup"], position=1)

    level1 = make_recipe(name="L1")
    add_ingredient(level1, make_ingredient("i1"), 10, gram, position=0)
    add_sub_recipe(level1, level2, 1, units["cup"], position=1)

    # Bounded by MAX_DEPTH, not by the 20 components: one base fetch plus one prefetch per
    # populated sub-recipe level (L1, L2, L3) = 4. Empty deeper levels add nothing. Kept tight
    # so a partial N+1 regression — a per-component or per-ingredient query creeping back in —
    # trips this immediately (task 05 review, NB3).
    with django_assert_max_num_queries(4):
        lines = flatten(level1)

    assert len(lines) == 20


def test_flatten_reuses_caller_prefetch(
    make_recipe,
    make_ingredient,
    gram,
    units,
    add_ingredient,
    add_sub_recipe,
    django_assert_max_num_queries,
):
    """A caller that already loaded the recipe through ``with_component_graph()`` — the meal
    planner over a week of dinners — must not have ``flatten`` re-issue the whole prefetch
    (task 05 review, NB2).
    """
    from recipes.models import Recipe

    sub = make_recipe(name="Sub", yield_quantity=Decimal("4.000"), yield_unit=units["cup"])
    add_ingredient(sub, make_ingredient("s1"), 10, gram, position=0)
    parent = make_recipe(name="Parent")
    add_ingredient(parent, make_ingredient("p1"), 10, gram, position=0)
    add_sub_recipe(parent, sub, 1, units["cup"], position=1)

    prefetched = Recipe.objects.with_component_graph().get(pk=parent.pk)

    with django_assert_max_num_queries(0):
        lines = flatten(prefetched)

    assert len(lines) == 2


def test_aggregate_merges_provenance():
    class _Unit:
        pk = 1
        dimension = "MASS"
        to_base_factor = Decimal("1")
        count_family = ""

    class _Ing:
        pk = 7
        name = "Flour"
        density_g_per_ml = None

    unit, ing = _Unit(), _Ing()
    lines = [
        FlatLine(ing, Decimal("100"), unit, ("Marinara",)),
        FlatLine(ing, Decimal("50"), unit, ("Meatballs",)),
    ]

    (merged,) = aggregate(lines)

    assert merged.quantity == Decimal("150")
    assert set(merged.from_recipes) == {"Marinara", "Meatballs"}
