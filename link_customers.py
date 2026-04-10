from apps.finance.models import DailySalesSheet, Receipt
from apps.jobs.models import Job
from apps.customers.models import CustomerProfile

# ── Customer 1: 0244742686 ─────────────────────────────────
c1 = CustomerProfile.objects.filter(phone__contains='0244742686').first()
print('Customer 1:', c1)

# Sheet WLB-0408-022 — the one job on it
sheet = DailySalesSheet.objects.filter(sheet_number='WLB-0408-022').first()
print('Sheet:', sheet)

if sheet:
    jobs = Job.objects.filter(daily_sheet=sheet)
    print(f'Jobs on sheet: {jobs.count()}')
    for j in jobs:
        print(f'  Job {j.job_number} customer before: {j.customer}')
        if c1:
            j.customer = c1
            j.save(update_fields=['customer'])
            print(f'  → linked to {c1.full_name}')

# RCP-WLB-2026-00595 → same customer
r1 = Receipt.objects.filter(receipt_number='RCP-WLB-2026-00595').first()
print('Receipt 00595:', r1)
if r1 and c1:
    j = r1.job
    print(f'  Job {j.job_number} customer before: {j.customer}')
    j.customer = c1
    j.save(update_fields=['customer'])
    print(f'  → linked to {c1.full_name}')

# ── Customer 2: 0200000001 ─────────────────────────────────
c2 = CustomerProfile.objects.filter(phone__contains='0200000001').first()
print('Customer 2:', c2)

# RCP-WLB-2026-00592 → c2
r2 = Receipt.objects.filter(receipt_number='RCP-WLB-2026-00592').first()
print('Receipt 00592:', r2)
if r2 and c2:
    j = r2.job
    print(f'  Job {j.job_number} customer before: {j.customer}')
    j.customer = c2
    j.save(update_fields=['customer'])
    print(f'  → linked to {c2.full_name}')

print('Done.')