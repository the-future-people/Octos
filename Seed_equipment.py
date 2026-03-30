from apps.inventory.models import BranchEquipment
from apps.organization.models import Branch

wlb = Branch.objects.get(code='WLB')

machinery = [
    {
        'name'         : 'Canon iR-ADV 5531i Printer',
        'quantity'     : 1,
        'manufacturer' : 'Canon',
        'model_number' : 'iR-ADV 5531i',
        'location'     : 'Front Desk',
        'condition'    : 'GOOD',
    },
    {
        'name'         : 'Dell 15" Monitor',
        'quantity'     : 1,
        'manufacturer' : 'Dell',
        'location'     : 'Front Desk',
        'condition'    : 'GOOD',
    },
    {
        'name'         : 'System Unit (Desktop PC)',
        'quantity'     : 1,
        'location'     : 'Front Desk',
        'condition'    : 'GOOD',
    },
    {
        'name'         : 'MasterPlus A4/A3 Laminator',
        'quantity'     : 1,
        'manufacturer' : 'MasterPlus',
        'location'     : 'Front Desk',
        'condition'    : 'GOOD',
    },
    {
        'name'         : 'MasterPlus Binding Machine',
        'quantity'     : 1,
        'manufacturer' : 'MasterPlus',
        'location'     : 'Front Desk',
        'condition'    : 'GOOD',
    },
    {
        'name'         : 'Canon SELPHY CP1000',
        'quantity'     : 1,
        'manufacturer' : 'Canon',
        'model_number' : 'SELPHY CP1000',
        'location'     : 'Front Desk',
        'condition'    : 'GOOD',
    },
    {
        'name'         : 'Huawei Broadband Receiver',
        'quantity'     : 1,
        'manufacturer' : 'Huawei',
        'location'     : 'Front Desk',
        'condition'    : 'GOOD',
    },
]

for item in machinery:
    eq, created = BranchEquipment.objects.get_or_create(
        branch = wlb,
        name   = item['name'],
        defaults = item,
    )
    print(f"  {'[+]' if created else '[=]'} {eq.asset_code} | {eq.name}")

print(f"\nTotal equipment: {BranchEquipment.objects.filter(branch=wlb).count()}")