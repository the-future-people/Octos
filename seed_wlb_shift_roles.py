"""
Seed: WLB ShiftRoleConfig records for all three roles on both shifts.
Run via:
  docker-compose --env-file .env.docker exec web python manage.py shell
  then: exec(open('seed_wlb_shift_roles.py').read())
"""

from datetime import time
from apps.hr.models import BranchShift, ShiftRoleConfig

# ── Fetch both WLB shifts ─────────────────────────────────
try:
    main_shift = BranchShift.objects.get(branch_id=2, name='WLB Main Shift')
    sat_shift  = BranchShift.objects.get(branch_id=2, name='WLB Saturday Shift')
except BranchShift.DoesNotExist as e:
    print(f"ERROR: {e}")
    raise

# ── Role configs ──────────────────────────────────────────
# Format: (role_name, start, end, job_lock, signoff, autoclose)
CONFIGS = [
    # Branch Manager — arrives early, leaves after closing
    ('BRANCH_MANAGER', time(7, 30),  time(20, 0),  60, 60, 60),
    # Cashier — standard branch hours
    ('CASHIER',        time(8, 0),   time(19, 30), 45, 45, None),
    # Attendant — ends slightly before cashier
    ('ATTENDANT',      time(8, 0),   time(19, 0),  0,  30, None),
]

created_count = 0
updated_count = 0

for shift in [main_shift, sat_shift]:
    for role_name, start, end, job_lock, signoff, autoclose in CONFIGS:
        obj, created = ShiftRoleConfig.objects.update_or_create(
            shift     = shift,
            role_name = role_name,
            defaults  = {
                'role_start_time'  : start,
                'role_end_time'    : end,
                'job_lock_buffer'  : job_lock,
                'signoff_buffer'   : signoff,
                'autoclose_buffer' : autoclose,
            }
        )
        status = 'Created' if created else 'Updated'
        if created:
            created_count += 1
        else:
            updated_count += 1
        print(f"  {status}: {shift.name} — {role_name} "
              f"({start.strftime('%H:%M')}–{end.strftime('%H:%M')})")

print(f"\nDone. {created_count} created, {updated_count} updated.")
print("\nAll ShiftRoleConfigs for WLB:")
for cfg in ShiftRoleConfig.objects.filter(shift__branch_id=2).select_related('shift'):
    print(f"  {cfg.shift.name} | {cfg.role_name:15} | "
          f"{cfg.effective_start_time.strftime('%H:%M')}–"
          f"{cfg.effective_end_time.strftime('%H:%M')} | "
          f"lock={cfg.job_lock_buffer}m signoff={cfg.signoff_buffer}m "
          f"autoclose={cfg.autoclose_buffer}m")