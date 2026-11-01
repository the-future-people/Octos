from django.apps import AppConfig


class EyeConfig(AppConfig):
    """
    The Eye of Agamotto: the owner's view of the whole business.

    Read-only. It owns no tables of its own; every figure is computed
    from the records the rest of Octos keeps, so it can never disagree
    with them.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.eye'
    verbose_name = 'Eye of Agamotto'
