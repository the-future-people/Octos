from apps.jobs.models import Job
from apps.customers.models import CustomerProfile

# Confirmed customer links from BM recall
links = {
    'FP-WLB-2026-00610': '0244742686',
    'FP-WLB-2026-00636': '0248370473',
    'FP-WLB-2026-00625': '0200000002',
    'FP-WLB-2026-00637': '0595236972',
    'FP-WLB-2026-00624': '0546299853',
}

print('Re-linking confirmed jobs...\n')
errors = []

for job_number, phone in links.items():
    try:
        job      = Job.objects.get(job_number=job_number)
        customer = CustomerProfile.objects.get(phone=phone)
        job.customer = customer
        job.save(update_fields=['customer'])
        print(f'  ✓ {job_number} → {customer.display_name} ({phone})')
    except Job.DoesNotExist:
        errors.append(f'  ✗ Job not found: {job_number}')
    except CustomerProfile.DoesNotExist:
        errors.append(f'  ✗ Customer not found: {phone} (for {job_number})')
    except Exception as e:
        errors.append(f'  ✗ {job_number}: {e}')

if errors:
    print('\nErrors:')
    for e in errors:
        print(e)

print(f'\nDone. {len(links) - len(errors)} jobs re-linked, {len(errors)} errors.')