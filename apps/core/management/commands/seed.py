from django.core.management.base import BaseCommand
from apps.accounts.models import Permission, Role


PERMISSIONS = [
    # Organization
    ('can_view_all_branches', 'View all branches system-wide'),
    ('can_create_branch', 'Create and edit branches'),
    ('can_view_belt', 'View belt-level data'),
    ('can_view_region', 'View region-level data'),

    # Jobs
    ('can_create_job', 'Create a new job'),
    ('can_route_job', 'Route a job to another branch'),
    ('can_update_job_status', 'Update job status'),
    ('can_view_all_jobs', 'View jobs across all branches'),

    # Finance
    ('can_confirm_payment', 'Confirm payment as cashier'),
    ('can_view_financials', 'View financial reports'),
    ('can_process_settlement', 'Process inter-branch settlements'),

    # HR
    ('can_manage_recruitment', 'Manage recruitment pipeline'),
    ('can_approve_employee', 'Approve new employee access'),
    ('can_request_transfer', 'Request employee transfer'),
    ('can_approve_transfer', 'Approve employee transfer'),

    # Inventory
    ('can_manage_inventory', 'Manage branch inventory'),

    # Analytics
    ('can_view_analytics', 'View analytics and reports'),

    # Communications
    ('can_access_inbox', 'Access branch unified inbox'),
    ('can_send_message', 'Send messages to customers'),

    # Design
    ('can_manage_design_jobs', 'Access and manage design jobs'),

    # Notifications
    ('can_view_notifications', 'View system notifications'),
]


ROLES = [
    {
        'name': 'SUPER_ADMIN',
        'display_name': 'Super Admin (CEO)',
        'permissions': [p[0] for p in PERMISSIONS],  # All permissions
    },
    {
        'name': 'HQ_HR_MANAGER',
        'display_name': 'HQ HR Manager',
        'permissions': [
            'can_manage_recruitment',
            'can_approve_employee',
            'can_request_transfer',
            'can_approve_transfer',
            'can_view_all_branches',
            'can_view_analytics',
            'can_view_notifications',
        ],
    },
    {
        'name': 'HQ_FACTORY_MANAGER',
        'display_name': 'HQ Factory Manager',
        'permissions': [
            'can_create_job',
            'can_update_job_status',
            'can_view_all_jobs',
            'can_manage_inventory',
            'can_view_analytics',
            'can_view_notifications',
        ],
    },
    {
        'name': 'BELT_MANAGER',
        'display_name': 'Belt Manager',
        'permissions': [
            'can_view_belt',
            'can_view_all_branches',
            'can_view_all_jobs',
            'can_view_financials',
            'can_view_analytics',
            'can_request_transfer',
            'can_view_notifications',
        ],
    },
    {
        'name': 'REGIONAL_MANAGER',
        'display_name': 'Regional Manager',
        'permissions': [
            'can_view_region',
            'can_view_all_branches',
            'can_view_all_jobs',
            'can_route_job',
            'can_view_financials',
            'can_view_analytics',
            'can_request_transfer',
            'can_view_notifications',
        ],
    },
    {
        'name': 'REGIONAL_HR_COORDINATOR',
        'display_name': 'Regional HR Coordinator',
        'permissions': [
            'can_manage_recruitment',
            'can_approve_employee',
            'can_view_region',
            'can_view_notifications',
        ],
    },
    {
        'name': 'BRANCH_MANAGER',
        'display_name': 'Branch Manager',
        'permissions': [
            'can_create_job',
            'can_route_job',
            'can_update_job_status',
            'can_view_all_jobs',
            'can_confirm_payment',
            'can_view_financials',
            'can_manage_inventory',
            'can_access_inbox',
            'can_send_message',
            'can_view_notifications',
        ],
    },
    {
        'name': 'ATTENDANT',
        'display_name': 'Attendant',
        'permissions': [
            'can_create_job',
            'can_update_job_status',
            'can_access_inbox',
            'can_send_message',
            'can_view_notifications',
        ],
    },
    {
        'name': 'CASHIER',
        'display_name': 'Cashier',
        'permissions': [
            'can_confirm_payment',
            'can_update_job_status',
            'can_view_notifications',
        ],
    },
    {
        'name': 'DESIGNER',
        'display_name': 'Designer',
        'permissions': [
            'can_manage_design_jobs',
            'can_update_job_status',
            'can_access_inbox',
            'can_send_message',
            'can_view_notifications',
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed the database with initial roles and permissions'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding permissions...')
        permission_map = {}
        for codename, description in PERMISSIONS:
            perm, created = Permission.objects.get_or_create(
                codename=codename,
                defaults={'description': description}
            )
            permission_map[codename] = perm
            if created:
                self.stdout.write(f'  ✓ Permission: {codename}')

        self.stdout.write('Seeding roles...')
        for role_data in ROLES:
            role, created = Role.objects.get_or_create(
                name=role_data['name'],
                defaults={'display_name': role_data['display_name']}
            )
            role.permissions.set([
                permission_map[p] for p in role_data['permissions']
            ])
            role.save()
            status = 'created' if created else 'updated'
            self.stdout.write(f'  ✓ Role {status}: {role.display_name}')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {len(PERMISSIONS)} permissions, {len(ROLES)} roles seeded.'
        ))