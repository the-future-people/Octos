"""
Managing the links between people and organisations, from the portal.

GET  customers/<id>/links/        a person's organisations, or an organisation's people
POST customers/<id>/links/        { other, role, named }   link them
PATCH customers/links/<id>/       { role, named }          change a link
POST customers/links/<id>/end/                             they've left (branch manager)

Anyone at the counter may link and change: they are there when Edward
says "I'm with Piwak". Ending a link is the branch manager's, because it
changes who a business expects to see ordering in its name. Every change
is written to both customers' edit logs.
"""

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

ORGS = ('BUSINESS', 'INSTITUTION')
ROLES = {'REP', 'STAFF', 'OWNER', 'MEMBER'}


# Who may end a link: the branch's manager, and the managers above a
# branch. Roles are read by name, as the portal shows them.
ENDS_LINKS = {'BRANCH MANAGER', 'BELT MANAGER', 'REGIONAL MANAGER'}


def _is_manager(user):
    role = str(getattr(user, 'role', '') or '').strip().upper()
    return bool(getattr(user, 'is_superuser', False) or role in ENDS_LINKS)


def _log(customer, user, what):
    from apps.customers.models import CustomerEditLog
    try:
        CustomerEditLog.objects.create(customer=customer, changed_by=user, field_name='link',
                                       old_value='', new_value=what[:500])
    except Exception:
        pass


def _row(m, side):
    other = m.organisation if side == 'person' else m.person
    return {
        'id': m.id,
        'customer': other.id,
        'name': other.company_name or other.full_name if side == 'person' else other.full_name,
        'phone': other.phone,
        'type': other.customer_type,
        'role': m.role,
        'named': m.named,
        'active': m.ended_at is None,
        'started_at': m.started_at.isoformat(),
        'ended_at': m.ended_at.isoformat() if m.ended_at else None,
    }


class CustomerLinksView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from apps.customers.models import CustomerProfile, Membership
        c = CustomerProfile.objects.filter(pk=pk).first()
        if c is None:
            return Response({'detail': 'No such customer.'}, status=status.HTTP_404_NOT_FOUND)
        side = 'organisation' if c.customer_type in ORGS else 'person'
        qs = (Membership.objects.filter(**{side: c})
              .select_related('person', 'organisation').order_by('ended_at', '-started_at'))
        return Response({'side': side, 'links': [_row(m, side) for m in qs],
                         'can_end': _is_manager(request.user)})

    def post(self, request, pk):
        from apps.customers.models import CustomerProfile, Membership
        c = CustomerProfile.objects.filter(pk=pk).first()
        other = CustomerProfile.objects.filter(pk=request.data.get('other')).first()
        if c is None or other is None:
            return Response({'detail': 'Choose who to link.'}, status=status.HTTP_400_BAD_REQUEST)
        if c.customer_type in ORGS:
            person, org = other, c
        else:
            person, org = c, other
        if person.customer_type in ORGS or org.customer_type not in ORGS:
            return Response({'detail': 'A link joins a person to a business or institution.'},
                            status=status.HTTP_400_BAD_REQUEST)
        role = str(request.data.get('role') or 'MEMBER').upper()
        if role not in ROLES:
            role = 'MEMBER'
        try:
            with transaction.atomic():
                m = Membership.objects.create(person=person, organisation=org, role=role,
                                              named=bool(request.data.get('named')))
        except IntegrityError:
            return Response({'detail': f'{person.full_name} is already linked to {org.company_name or org.full_name}.'},
                            status=status.HTTP_400_BAD_REQUEST)
        what = f'linked: {person.full_name} {m.get_role_display()} of {org.company_name or org.full_name}'
        _log(person, request.user, what)
        _log(org, request.user, what)
        side = 'organisation' if c.customer_type in ORGS else 'person'
        return Response(_row(m, side), status=status.HTTP_201_CREATED)


class LinkView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        from apps.customers.models import Membership
        m = Membership.objects.filter(pk=pk, ended_at__isnull=True).select_related('person', 'organisation').first()
        if m is None:
            return Response({'detail': 'No such link.'}, status=status.HTTP_404_NOT_FOUND)
        changes = []
        role = str(request.data.get('role') or '').upper()
        if role in ROLES and role != m.role:
            m.role = role
            changes.append(f'role {role.lower()}')
        if 'named' in request.data and bool(request.data['named']) != m.named:
            m.named = bool(request.data['named'])
            changes.append('named' if m.named else 'no longer named')
        if changes:
            m.save(update_fields=['role', 'named'])
            what = f'link changed: {m.person.full_name} at {m.organisation.company_name or m.organisation.full_name}: {", ".join(changes)}'
            _log(m.person, request.user, what)
            _log(m.organisation, request.user, what)
        return Response({'id': m.id, 'role': m.role, 'named': m.named})


class LinkEndView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.customers.models import Membership
        if not _is_manager(request.user):
            return Response({'detail': 'Ending a link is for the branch manager.'}, status=status.HTTP_403_FORBIDDEN)
        m = Membership.objects.filter(pk=pk).select_related('person', 'organisation').first()
        if m is None:
            return Response({'detail': 'No such link.'}, status=status.HTTP_404_NOT_FOUND)
        m.end()
        what = f'link ended: {m.person.full_name} has left {m.organisation.company_name or m.organisation.full_name}'
        _log(m.person, request.user, what)
        _log(m.organisation, request.user, what)
        return Response({'id': m.id, 'ended_at': m.ended_at.isoformat()})