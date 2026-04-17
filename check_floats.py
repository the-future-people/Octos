from apps.finance.models import DailySalesSheet
from django.utils import timezone

sheets = DailySalesSheet.objects.filter(
    branch__name='Westland Branch'
).order_by('date').values('id', 'date', 'sheet_number', 'status')

for s in sheets:
    print(s)