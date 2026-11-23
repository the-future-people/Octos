from django.apps import AppConfig


class PartnersConfig(AppConfig):
    """
    Farhat Trade Partners (23 Nov 2026): small print shops, business centres
    and cyber cafés send Farhat the work their machines can't do, through a
    portal on Print Octos. Farhat prints; the partner keeps their customer.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.partners'
    verbose_name = 'Trade partners'
