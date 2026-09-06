"""The seeded generator (``Plan/08-Meal-Planner/test-plan.md``, "Generator").

**Every test pins a seed.** A generator test that leans on unseeded randomness fails one
morning for no reason, gets deleted, and then the planner is untested.

Composition-dependent behaviour (``test_compose.py`` and the BALANCED-fallback-to-recipes
path) belongs to 08.5 and is out of this run — every BALANCED test here uses dishes that
already cover all three roles.
"""

from __future__ import annotations

import time

import pytest

from planner.models import MealPlanEntry
from planner.services.generate import MAX_BACKTRACKS, generate_plan
from recipes.models import RecipeRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def make_pool_dish(make_dish, make_recipe, add_component):
    def _make(name, *, owner, role=RecipeRole.OTHER, tags=None) -> object:
        dish = make_dish(name, owner=owner, tags=tags)
        add_component(dish, make_recipe(f"{name} recipe", owner=owner, role=role))
        return dish

    return _make


def _filled(result) -> list:
    return [entry for entry in result.entries if entry.dish is not None]


def _entry_key(entry: MealPlanEntry) -> tuple:
    return (entry.day_index, entry.slot, entry.dish_id)


def test_same_seed_produces_identical_plan(make_pool_dish, make_profile, alice):
    for i in range(12):
        make_pool_dish(f"Dish {i}", owner=alice)
    profile = make_profile(owner=alice)

    first = generate_plan(alice, profile, seed=4242, days=7)
    second = generate_plan(alice, profile, seed=4242, days=7)

    assert [_entry_key(e) for e in first.entries] == [_entry_key(e) for e in second.entries]
    assert first.unfilled == second.unfilled
    assert first.reasons == second.reasons


def test_different_seed_produces_different_plan(make_pool_dish, make_profile, alice):
    for i in range(20):
        make_pool_dish(f"Dish {i}", owner=alice)
    profile = make_profile(owner=alice)

    a = generate_plan(alice, profile, seed=1, days=7)
    b = generate_plan(alice, profile, seed=2, days=7)

    assert [_entry_key(e) for e in a.entries] != [_entry_key(e) for e in b.entries]


def test_generates_requested_number_of_days(make_pool_dish, make_profile, alice):
    for i in range(10):
        make_pool_dish(f"Dish {i}", owner=alice)
    profile = make_profile(owner=alice)

    result = generate_plan(alice, profile, seed=7, days=4, slots=["DINNER"])

    assert {entry.day_index for entry in result.entries} == {0, 1, 2, 3}
    assert len(result.entries) == 4


def test_generates_all_requested_slots(make_pool_dish, make_profile, alice):
    for i in range(12):
        make_pool_dish(f"Dish {i}", owner=alice)
    profile = make_profile(owner=alice)

    result = generate_plan(alice, profile, seed=7, days=3, slots=["BREAKFAST", "DINNER"])

    assert sorted({entry.slot for entry in result.entries}) == ["BREAKFAST", "DINNER"]
    assert len(result.entries) == 6


def test_respects_tag_limit(make_pool_dish, make_profile, make_tag, alice):
    chicken = make_tag("chicken")
    make_pool_dish("Chicken A", owner=alice, tags=[chicken])
    make_pool_dish("Chicken B", owner=alice, tags=[chicken])
    for i in range(8):
        make_pool_dish(f"Plain {i}", owner=alice)

    profile = make_profile(owner=alice, tag_limits={"chicken": 1})
    result = generate_plan(alice, profile, seed=99, days=7, slots=["DINNER"])

    chicken_dishes = [e for e in _filled(result) if e.dish.tags.filter(pk=chicken.pk).exists()]
    assert len(chicken_dishes) == 1
    assert len(_filled(result)) == 7


def test_tag_limit_zero_excludes_entirely(make_pool_dish, make_profile, make_tag, alice):
    beef = make_tag("beef")
    make_pool_dish("Beef", owner=alice, tags=[beef])
    for i in range(5):
        make_pool_dish(f"Plain {i}", owner=alice)

    profile = make_profile(owner=alice, tag_limits={"beef": 0})
    result = generate_plan(alice, profile, seed=3, days=5, slots=["DINNER"])

    assert all(not e.dish.tags.filter(pk=beef.pk).exists() for e in _filled(result))


def test_locked_entries_preserved_on_regenerate(make_pool_dish, make_profile, alice):
    for i in range(10):
        make_pool_dish(f"Dish {i}", owner=alice)
    pinned = make_pool_dish("Pinned", owner=alice)
    profile = make_profile(owner=alice)

    locked = [MealPlanEntry(day_index=1, slot="DINNER", dish=pinned, is_locked=True)]
    result = generate_plan(alice, profile, seed=5, days=7, slots=["DINNER"], locked=locked)

    day1 = next(e for e in result.entries if e.day_index == 1)
    assert day1.dish_id == pinned.pk
    assert day1.is_locked is True


def test_locked_entries_consume_tag_budget(make_pool_dish, make_profile, make_tag, alice):
    chicken = make_tag("chicken")
    locked_dish = make_pool_dish("Locked chicken", owner=alice, tags=[chicken])
    make_pool_dish("Chicken B", owner=alice, tags=[chicken])
    make_pool_dish("Chicken C", owner=alice, tags=[chicken])
    for i in range(6):
        make_pool_dish(f"Plain {i}", owner=alice)

    profile = make_profile(owner=alice, tag_limits={"chicken": 1})
    locked = [MealPlanEntry(day_index=0, slot="DINNER", dish=locked_dish, is_locked=True)]
    result = generate_plan(alice, profile, seed=11, days=7, slots=["DINNER"], locked=locked)

    unlocked_chicken = [
        e for e in _filled(result) if not e.is_locked and e.dish.tags.filter(pk=chicken.pk).exists()
    ]
    assert unlocked_chicken == []


def test_balanced_template_covers_roles(make_balanced_dish, make_profile, alice):
    for _ in range(8):
        make_balanced_dish(owner=alice)
    profile = make_profile(owner=alice, dish_template="BALANCED")

    result = generate_plan(alice, profile, seed=8, days=5, slots=["DINNER"])

    assert len(_filled(result)) == 5
    covered: set[str] = set()
    for entry in _filled(result):
        covered |= {component.recipe.role for component in entry.dish.components.all()}
    assert {RecipeRole.PROTEIN, RecipeRole.CARB, RecipeRole.VEGETABLE} <= covered


def test_one_pot_template_selects_one_pot(make_pool_dish, make_profile, alice):
    one_pots = [make_pool_dish(f"Pot {i}", owner=alice, role=RecipeRole.ONE_POT) for i in range(4)]
    for i in range(5):
        make_pool_dish(f"Plain {i}", owner=alice)

    profile = make_profile(owner=alice, dish_template="ONE_POT")
    result = generate_plan(alice, profile, seed=6, days=7, slots=["DINNER"])

    first_four = _filled(result)[:4]
    assert {e.dish_id for e in first_four} == {d.pk for d in one_pots}


def test_mix_template_varies(make_balanced_dish, make_pool_dish, make_profile, alice):
    """MIX alternates its preferred sub-template slot by slot (``design.md`` §5). With a pool
    of purely-balanced and purely-one-pot dishes the alternation is directly observable: no
    two adjacent slots share a kind, and both kinds are used in equal measure. A generator
    that ignored MIX and picked uniformly from the pool would not produce this pattern.
    """
    balanced = [make_balanced_dish(f"Bal {i}", owner=alice) for i in range(3)]
    one_pots = [
        make_pool_dish(f"Pot {i}", owner=alice, role=RecipeRole.ONE_POT) for i in range(3)
    ]
    balanced_ids = {d.pk for d in balanced}
    one_pot_ids = {d.pk for d in one_pots}

    profile = make_profile(owner=alice, dish_template="MIX")
    result = generate_plan(alice, profile, seed=2, days=6, slots=["DINNER"])

    filled = _filled(result)
    assert len(filled) == 6

    kinds = [
        "B" if e.dish_id in balanced_ids else "O" if e.dish_id in one_pot_ids else "?"
        for e in filled
    ]
    assert "?" not in kinds
    assert kinds.count("B") == 3
    assert kinds.count("O") == 3
    assert all(a != b for a, b in zip(kinds, kinds[1:], strict=False))


def test_favorites_bias_increases_selection_rate(
    make_pool_dish, make_profile, set_dish_stats, alice
):
    dishes = [make_pool_dish(f"Dish {i}", owner=alice) for i in range(4)]
    favourite = dishes[0]
    set_dish_stats(alice, favourite, is_favorite=True)

    profile = make_profile(owner=alice, favorites_bias="3.0")

    trials = 200
    hits = 0
    for seed in range(trials):
        result = generate_plan(alice, profile, seed=seed, days=1, slots=["DINNER"])
        if _filled(result)[0].dish_id == favourite.pk:
            hits += 1

    # Unweighted rate is 1/4; a 3x bias lifts the expected rate to 3/6 = 0.5.
    assert hits / trials > 0.38


def test_no_duplicate_dishes_within_plan(make_pool_dish, make_profile, alice):
    for i in range(10):
        make_pool_dish(f"Dish {i}", owner=alice)
    profile = make_profile(owner=alice)

    result = generate_plan(alice, profile, seed=1, days=7, slots=["DINNER"])

    dish_ids = [e.dish_id for e in _filled(result)]
    assert len(dish_ids) == len(set(dish_ids)) == 7


def test_partial_plan_when_pool_too_small(make_pool_dish, make_profile, alice):
    make_pool_dish("Only A", owner=alice)
    make_pool_dish("Only B", owner=alice)
    profile = make_profile(owner=alice)

    result = generate_plan(alice, profile, seed=1, days=7, slots=["DINNER"])

    assert len(_filled(result)) == 2
    assert len(result.unfilled) == 5
    assert len(result.entries) == 7


def test_unfilled_slots_have_reasons(make_pool_dish, make_profile, alice):
    make_pool_dish("Only A", owner=alice)
    profile = make_profile(owner=alice)

    result = generate_plan(alice, profile, seed=1, days=4, slots=["DINNER"])

    assert len(result.reasons) == len(result.unfilled) == 3
    assert all(isinstance(reason, str) and reason for reason in result.reasons)


def test_empty_pool_returns_all_unfilled_with_reason(make_profile, alice):
    profile = make_profile(owner=alice)

    result = generate_plan(alice, profile, seed=1, days=7, slots=["DINNER"])

    assert _filled(result) == []
    assert len(result.unfilled) == 7
    assert all("no dishes yet" in reason.lower() for reason in result.reasons)


def test_never_hangs_on_impossible_constraints(make_pool_dish, make_profile, make_tag, alice):
    chicken = make_tag("chicken")
    for i in range(3):
        make_pool_dish(f"Chicken {i}", owner=alice, tags=[chicken])

    profile = make_profile(owner=alice, tag_limits={"chicken": 1})

    started = time.monotonic()
    result = generate_plan(alice, profile, seed=1, days=7, slots=["DINNER"])
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
    assert len(_filled(result)) == 1
    assert len(result.unfilled) == 6


def test_backtracking_bounded(make_pool_dish, make_profile, make_tag, alice):
    chicken = make_tag("chicken")
    make_pool_dish("Chicken A", owner=alice, tags=[chicken])
    make_pool_dish("Chicken B", owner=alice, tags=[chicken])
    make_pool_dish("Plain", owner=alice)

    profile = make_profile(owner=alice, tag_limits={"chicken": 1})
    result = generate_plan(alice, profile, seed=1, days=3, slots=["DINNER"])

    assert 0 < result.backtracks <= MAX_BACKTRACKS
    assert len(result.unfilled) >= 1


def test_generation_does_not_persist(make_pool_dish, make_profile, alice):
    for i in range(8):
        make_pool_dish(f"Dish {i}", owner=alice)
    profile = make_profile(owner=alice)

    generate_plan(alice, profile, seed=1, days=7, slots=["DINNER"])

    from planner.models import MealPlan

    assert MealPlan.objects.count() == 0
    assert MealPlanEntry.objects.count() == 0


def test_result_carries_seed(make_pool_dish, make_profile, alice):
    make_pool_dish("A", owner=alice)
    profile = make_profile(owner=alice)

    result = generate_plan(alice, profile, seed=555, days=1, slots=["DINNER"])

    assert result.seed == 555
