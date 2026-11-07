"""
Octos's own account (7 Nov 2026): the role OCTOS, allowed to create and
issue proformas and nothing else, and a user "Octos" with it, that can never
sign in (no password, not active). Proformas it issues show "issued by
Octos" in the Branch Manager's list.

    python manage.py setup_octos

Safe to run any number of times.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

EMAIL = 'octos@octos.internal'


def _fill_required(model, given):
    """Add a plain value for any required field the model would refuse to save without."""
    out = dict(given)
    for f in model._meta.concrete_fields:
        if (f.name in out or f.primary_key or f.null or f.has_default() or f.is_relation
                or getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False)):
            continue
        kind = f.get_internal_type()
        if kind in ('CharField', 'TextField', 'SlugField'):
            out[f.name] = f.choices[0][0] if f.choices else ('' if f.blank else 'Octos')
        elif kind == 'BooleanField':
            out[f.name] = False
    return out


class Command(BaseCommand):
    help = "Octos's own account, for issuing proformas (safe to run again)."

    @transaction.atomic
    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        from apps.accounts.models.role import Role
        User = get_user_model()

        role = Role.objects.filter(name='OCTOS').first()
        if role is None:
            role = Role.objects.create(**_fill_required(Role, {
                'name': 'OCTOS', 'scope': Role.SCOPE_HQ, 'is_constrained': False,
            }))
            self.stdout.write('Role OCTOS: created (it may create and issue proformas, nothing else)')
        else:
            self.stdout.write('Role OCTOS: already there')

        user = User.objects.filter(email=EMAIL).first()
        if user is None:
            given = _fill_required(User, {
                'email': EMAIL, 'first_name': 'Octos', 'last_name': '(assistant)',
                'employee_id': 'OCTOS', 'role': role, 'is_active': False,
            })
            given.pop('password', None)
            user = User.objects.create_user(**given)   # no password: it can never sign in
            self.stdout.write('User Octos: created, with no password and not active')
        else:
            if user.role_id != role.pk:
                user.role = role
                user.save(update_fields=['role'])
            self.stdout.write('User Octos: already there')
