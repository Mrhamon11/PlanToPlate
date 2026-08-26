"""Throwaway Django generic views exercising ``OwnedObjectMixin`` (03.9) against
``core.tests.models.DummyOwned`` — see that module's docstring for why these are test-only.
Wired only via ``core/tests/urls.py``, activated per test module with
``@pytest.mark.urls("core.tests.urls")`` rather than mounted in ``config.urls``.
"""

from __future__ import annotations

from django.views.generic import DetailView, ListView, UpdateView

from core.mixins import OwnedObjectMixin
from core.tests.models import DummyOwned


class DummyListView(OwnedObjectMixin, ListView):
    model = DummyOwned
    template_name = "core_test_fixtures/dummy_list.html"


class DummyDetailView(OwnedObjectMixin, DetailView):
    model = DummyOwned
    template_name = "core_test_fixtures/dummy_detail.html"


class DummyUpdateView(OwnedObjectMixin, UpdateView):
    model = DummyOwned
    fields = ["name"]
    template_name = "core_test_fixtures/dummy_form.html"
    success_url = "/dummy-html/"


class DummyUnsafeUpdateView(OwnedObjectMixin, UpdateView):
    """Never wired into a URLconf -- exists only so core/tests/test_view_mixins.py can prove
    OwnedObjectMixin.get_form_class() refuses a form that reopens the write-path OwnedSerializer
    closes on the API side (03.8a rework, security finding 4).
    """

    model = DummyOwned
    fields = ["name", "visibility"]
    template_name = "core_test_fixtures/dummy_form.html"
    success_url = "/dummy-html/"
