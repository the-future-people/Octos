from apps.jobs.models import Job

# Unlink all jobs on sheet 111 from customer 0244742686
# FP-WLB-2026-00608 (sheet=105, Apr 7) was legitimate — leave it alone

job_numbers = [
    'FP-WLB-2026-00610', 'FP-WLB-2026-00611', 'FP-WLB-2026-00612',
    'FP-WLB-2026-00613', 'FP-WLB-2026-00614', 'FP-WLB-2026-00615',
    'FP-WLB-2026-00616', 'FP-WLB-2026-00617', 'FP-WLB-2026-00618',
    'FP-WLB-2026-00619', 'FP-WLB-2026-00620', 'FP-WLB-2026-00621',
    'FP-WLB-2026-00622', 'FP-WLB-2026-00623', 'FP-WLB-2026-00624',
    'FP-WLB-2026-00625', 'FP-WLB-2026-00626', 'FP-WLB-2026-00627',
    'FP-WLB-2026-00628', 'FP-WLB-2026-00629', 'FP-WLB-2026-00630',
    'FP-WLB-2026-00631', 'FP-WLB-2026-00632', 'FP-WLB-2026-00633',
    'FP-WLB-2026-00634', 'FP-WLB-2026-00635', 'FP-WLB-2026-00636',
    'FP-WLB-2026-00637', 'FP-WLB-2026-00638',
]

print(f'Unlinking {len(job_numbers)} jobs from customer 0244742686...')
updated = Job.objects.filter(job_number__in=job_numbers).update(customer=None)
print(f'Done — {updated} jobs unlinked.')

# Verify
from apps.customers.models import CustomerProfile
customer = CustomerProfile.objects.get(phone='0244742686')
remaining = Job.objects.filter(customer=customer).count()
print(f'Jobs still linked to 0244742686: {remaining} (should be 1 — FP-WLB-2026-00608)')