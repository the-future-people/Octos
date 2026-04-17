from apps.finance.models import DailySalesSheet, CashierFloat
from apps.accounts.models import CustomUser
from django.utils import timezone
from decimal import Decimal

# Find Westland Branch cashier
cashier = CustomUser.objects.filter(
    branch__name='Westland Branch',
    role__name='CASHIER',
    is_active=True,
).first()
print('Cashier:', cashier)

# Find BM
bm = CustomUser.objects.filter(
    branch__name='Westland Branch',
    role__name='BRANCH_MANAGER',
    is_active=True,
).first()
print('BM:', bm)

sheet = DailySalesSheet.objects.filter(
    branch__name='Westland Branch',
    date=timezone.localdate(),
    status='OPEN'
).first()
print('Sheet:', sheet)

if not cashier or not sheet:
    print('ERROR: missing cashier or sheet')
else:
    existing = CashierFloat.objects.filter(daily_sheet=sheet, cashier=cashier).first()
    if existing:
        print('Float already exists:', existing.id, 'signed_off:', existing.is_signed_off)
    else:
        f = CashierFloat.objects.create(
            cashier       = cashier,
            daily_sheet   = sheet,
            opening_float = Decimal('50.00'),
            float_set_by  = bm or cashier,
            float_set_at  = timezone.now(),
        )
        print('Float created:', f.id, 'amount:', f.opening_float)