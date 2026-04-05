"""
Seed: FINANCE role + HQ Finance reviewer user
Run via:
  docker-compose --env-file .env.docker exec web python manage.py shell
  then: exec(open('seed_finance_user.py').read())
"""

from django.utils import timezone
from apps.accounts.models import CustomUser, Role

# ── 1. Create FINANCE role if it doesn't exist ────────────────────────────
role, role_created = Role.objects.get_or_create(
    name='FINANCE',
    defaults={'description': 'HQ Finance reviewer — reviews and clears monthly closes'},
)
if role_created:
    print(f"Created role: FINANCE (id={role.id})")
else:
    print(f"Role already exists: FINANCE (id={role.id})")

# ── 2. Create Finance user ────────────────────────────────────────────────
user, created = CustomUser.objects.get_or_create(
    email='finance@farhat.com',
    defaults={
        'first_name'  : 'Abena',
        'last_name'   : 'Owusu',
        'employee_id' : 'FIN-001',
        'role'        : role,
        'region'      : None,
        'branch'      : None,
        'is_active'   : True,
        'approved_at' : timezone.now(),
    }
)

if created:
    user.set_password('Farhat@2026')
    user.save()
    print(f"Created Finance user: {user.full_name}")
    print(f"  Email      : finance@farhat.com")
    print(f"  Password   : Farhat@2026")
    print(f"  Employee ID: FIN-001")
    print(f"  Branch     : None (HQ level)")
    print(f"  User ID    : {user.id}")
else:
    print(f"Finance user already exists: {user.full_name} (id={user.id})")
    print(f"  Branch: {user.branch}")