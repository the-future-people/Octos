"""
Seed: Regional Manager user for Accra Region
Run via:
  docker-compose --env-file .env.docker exec web python manage.py shell
  then: exec(open('seed_regional_manager.py').read())
"""

from apps.accounts.models import CustomUser, Role
from apps.organization.models import Region

# ── Guards ────────────────────────────────────────────────
role = Role.objects.filter(name='REGIONAL_MANAGER').first()
if not role:
    print("ERROR: REGIONAL_MANAGER role not found. Aborting.")
else:
    region = Region.objects.filter(name='Accra Region').first()
    if not region:
        print("ERROR: Accra Region not found. Aborting.")
    else:
        user, created = CustomUser.objects.get_or_create(
            email='regional@farhat.com',
            defaults={
                'first_name'  : 'Esi',
                'last_name'   : 'Asante',
                'employee_id' : 'RGM-001',
                'role'        : role,
                'region'      : region,
                'branch'      : None,
                'is_active'   : True,
                'approved_at' : __import__('django.utils.timezone', fromlist=['timezone']).timezone.now(),
            }
        )

        if created:
            user.set_password('Farhat@2026')
            user.save()
            print(f"Created Regional Manager: {user.full_name}")
            print(f"  Email      : regional@farhat.com")
            print(f"  Password   : Farhat@2026")
            print(f"  Employee ID: RGM-001")
            print(f"  Region     : {region.name}")
            print(f"  User ID    : {user.id}")
        else:
            print(f"Regional Manager already exists: {user.full_name} (id={user.id})")
            print(f"  Region: {user.region}")