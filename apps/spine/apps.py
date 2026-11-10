from django.apps import AppConfig


class SpineConfig(AppConfig):
    """
    The spine: Octos's record of everything that happens (Layer 1, 10 Nov 2026).
    Other apps tell the spine what happened; the spine never changes anything else.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.spine'
    verbose_name = 'Spine (event log)'

    def ready(self):
        # Connect the one signal the spine listens to (a Job being created).
        # Everything else calls record() explicitly; see apps/spine/jobs.py.
        from apps.spine import jobs  # noqa: F401
