"""RecipeBook model behaviour (``Plan/06-Dishes-And-RecipeBooks/test-plan.md``,
"RecipeBook models").
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from core.models import OwnedModel
from meals.models import RecipeBook, RecipeBookEntry

pytestmark = pytest.mark.django_db


def test_book_is_owned():
    assert issubclass(RecipeBook, OwnedModel)


def test_recipe_unique_per_book(make_book, make_recipe):
    book = make_book()
    recipe = make_recipe()
    RecipeBookEntry.objects.create(book=book, recipe=recipe)

    with pytest.raises(IntegrityError), transaction.atomic():
        RecipeBookEntry.objects.create(book=book, recipe=recipe)


def test_recipe_can_be_in_multiple_books(make_book, make_recipe):
    recipe = make_recipe()
    books = [make_book(f"Book {i}") for i in range(3)]
    for book in books:
        RecipeBookEntry.objects.create(book=book, recipe=recipe)

    assert recipe.book_entries.count() == 3
    assert {entry.book_id for entry in recipe.book_entries.all()} == {b.pk for b in books}


def test_entries_ordered_by_section_then_position(make_book, make_recipe):
    book = make_book()
    RecipeBookEntry.objects.create(
        book=book, recipe=make_recipe("A"), section="Weeknight", position=1
    )
    RecipeBookEntry.objects.create(
        book=book, recipe=make_recipe("B"), section="Desserts", position=0
    )
    RecipeBookEntry.objects.create(
        book=book, recipe=make_recipe("C"), section="Weeknight", position=0
    )

    ordered = [(e.section, e.position) for e in book.entries.all()]
    assert ordered == [("Desserts", 0), ("Weeknight", 0), ("Weeknight", 1)]


def test_deleting_recipe_removes_entry(make_book, make_recipe):
    """CASCADE — a deleted recipe leaves its books quietly, no ProtectedError."""
    book = make_book()
    recipe = make_recipe("Doomed")
    RecipeBookEntry.objects.create(book=book, recipe=recipe)

    recipe.delete()

    assert book.entries.count() == 0
    assert RecipeBook.objects.filter(pk=book.pk).exists()


def test_section_optional(make_book, make_recipe):
    book = make_book()
    entry = RecipeBookEntry.objects.create(book=book, recipe=make_recipe())

    assert entry.section == ""
    entry.full_clean()  # blank section must not be a validation error
