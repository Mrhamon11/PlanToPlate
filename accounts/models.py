from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """The project's user model — see MILESTONES.md section 4.

    Subclasses ``AbstractUser`` rather than ``AbstractBaseUser`` so the admin, permissions,
    and password machinery come for free, which is the right trade for a 20-user app.
    Admin status uses the inherited ``is_staff`` / ``is_superuser`` rather than a new field —
    inventing a parallel "is admin" flag would create a second source of truth.
    """

    must_change_password = models.BooleanField(default=False)
    temp_password_expires_at = models.DateTimeField(null=True, blank=True)
