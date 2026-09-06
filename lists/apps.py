from django.apps import AppConfig


class ListsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lists"
    label = "lists"

    def ready(self) -> None:
        # Registers the pre_delete receivers that tombstone content-only list items so a
        # SET_NULL on a deleted recipe/dish/ingredient does not violate the has-content check
        # constraint (see lists/signals.py).
        from lists import signals  # noqa: F401
