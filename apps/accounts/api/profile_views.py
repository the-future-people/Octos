"""
Staff profiles (15 Nov 2026). See accounts/profiles.py.

  GET   /api/v1/accounts/profile/?period=week     your own card and numbers
  PATCH /api/v1/accounts/profile/                 {phone, email}: asks the Branch Manager
  POST  /api/v1/accounts/profile/photo/           multipart "photo": asks the Branch Manager
  DELETE /api/v1/accounts/profile/photo/          asks to remove it
  DELETE /api/v1/accounts/profile/changes/<id>/   take back a request still waiting

  GET   /api/v1/accounts/staff/?period=week       the branch's cards (Branch Manager)
  PATCH /api/v1/accounts/staff/<id>/              {phone} (Branch Manager, his branch)
  POST  /api/v1/accounts/staff/<id>/photo/        multipart "photo" (Branch Manager, his branch)
  DELETE /api/v1/accounts/staff/<id>/photo/
  POST  /api/v1/accounts/staff/changes/<id>/approve/
  POST  /api/v1/accounts/staff/changes/<id>/reject/   {note}

A Branch Manager's own changes apply at once; everyone else's wait for him
(16 Nov 2026).
"""
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import profiles
from apps.accounts.models import CustomUser
from apps.accounts.on_shift import on_shift
from apps.accounts.system import OCTOS_ROLE

# The order roles appear on the Staff page.
ROLE_ORDER = ['BRANCH_MANAGER', 'FLOW_COORDINATOR', 'COORDINATOR', 'CASHIER', 'ATTENDANT', 'OPERATOR']


def _period(request):
    period = request.query_params.get('period', 'week')
    return period if period in profiles.PERIODS else 'week'


def _refused(exc):
    return Response({'detail': str(exc)}, status=400)


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(profiles.card(request.user, _period(request)))

    def patch(self, request):
        user = request.user
        try:
            for key, field, current in (('phone', 'PHONE', user.phone), ('email', 'EMAIL', user.email)):
                if key in request.data and (request.data.get(key) or '').strip() != (current or ''):
                    profiles.ask(user, field, request.data.get(key) or '')
        except profiles.ProfileRefused as exc:
            return _refused(exc)
        user.refresh_from_db()
        return Response(profiles.card(user, _period(request)))


class ProfilePhotoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        try:
            profiles.ask(request.user, 'PHOTO', upload=request.FILES.get('photo'))
        except profiles.ProfileRefused as exc:
            return _refused(exc)
        request.user.refresh_from_db()
        return Response(profiles.card(request.user, _period(request)))

    def delete(self, request):
        if request.user.photo:
            profiles.ask(request.user, 'PHOTO', remove=True)
            request.user.refresh_from_db()
        return Response(profiles.card(request.user, _period(request)))


class ProfileChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            profiles.withdraw(request.user, pk)
        except profiles.ProfileRefused as exc:
            return _refused(exc)
        return Response(profiles.card(request.user, _period(request)))


def _manager_or_403(request):
    user = request.user
    if not (user.role_id and user.role.name == 'BRANCH_MANAGER' and user.branch_id):
        return Response({'detail': 'Only a Branch Manager can manage staff profiles.'}, status=403)
    return None


def _member(request, pk):
    """The staff member, if this manager may change them; else None."""
    member = CustomUser.objects.select_related('role', 'branch').filter(pk=pk).first()
    if member is None or not profiles.may_manage(request.user, member):
        return None
    return member


class StaffListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        refused = _manager_or_403(request)
        if refused:
            return refused
        period = _period(request)
        branch = request.user.branch
        people = (CustomUser.objects.filter(branch=branch, is_superuser=False)
                  .exclude(role__name=OCTOS_ROLE).select_related('role', 'branch'))
        presence = {p['id']: p for p in on_shift(branch)['staff']}

        cards = []
        for person in people:
            row = profiles.card(person, period)
            seen = presence.get(person.pk)
            row['presence'] = {'state': seen['state'], 'label': seen['label']} if seen else None
            cards.append(row)
        rank = {name: i for i, name in enumerate(ROLE_ORDER)}
        cards.sort(key=lambda c: (not c['is_active'], rank.get(c['role'], len(ROLE_ORDER)), c['full_name'].lower()))

        counts = {}
        for c in cards:
            if c['is_active']:
                counts[c['role_label'] or 'Other'] = counts.get(c['role_label'] or 'Other', 0) + 1
        on = sum(1 for c in cards if c['presence'] and c['presence']['state'] != 'off')
        waiting = [{**profiles.pending_row(c), 'full_name': c.user.full_name, 'first_name': c.user.first_name,
                    'role_label': profiles.ROLE_LABELS.get(c.user.role.name if c.user.role_id else '', ''),
                    'current': {'PHONE': c.user.phone, 'EMAIL': c.user.email}.get(c.field, ''),
                    'current_photo_url': profiles.signed_url(c.user.photo) if c.field == 'PHOTO' else None}
                   for c in profiles.waiting_for(request.user)]
        return Response({'period': period, 'staff': cards, 'counts': counts, 'on': on, 'waiting': waiting})


class StaffChangeDecisionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, decision):
        if decision not in ('approve', 'reject'):
            return Response({'detail': 'Approve or reject.'}, status=404)
        refused = _manager_or_403(request)
        if refused:
            return refused
        try:
            if decision == 'approve':
                profiles.approve(request.user, pk)
            else:
                profiles.reject(request.user, pk, request.data.get('note', ''))
        except profiles.ProfileRefused as exc:
            return _refused(exc)
        return Response({'ok': True})


class StaffMemberView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        refused = _manager_or_403(request)
        if refused:
            return refused
        member = _member(request, pk)
        if member is None:
            return Response({'detail': 'Not someone at your branch.'}, status=404)
        try:
            if 'phone' in request.data and (request.data.get('phone') or '').strip() != (member.phone or ''):
                profiles.set_phone(member, request.data.get('phone', ''), by=request.user)
            if 'email' in request.data and (request.data.get('email') or '').strip().lower() != member.email.lower():
                profiles.set_email(member, request.data.get('email', ''), by=request.user)
        except profiles.ProfileRefused as exc:
            return _refused(exc)
        member.refresh_from_db()
        return Response(profiles.card(member, _period(request)))


class StaffPhotoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, pk):
        refused = _manager_or_403(request)
        if refused:
            return refused
        member = _member(request, pk)
        if member is None:
            return Response({'detail': 'Not someone at your branch.'}, status=404)
        upload = request.FILES.get('photo')
        if upload is None:
            return Response({'detail': 'Choose a photo first.'}, status=400)
        try:
            profiles.set_photo(member, upload, by=request.user)
        except profiles.ProfileRefused as exc:
            return _refused(exc)
        return Response(profiles.card(member, _period(request)))

    def delete(self, request, pk):
        refused = _manager_or_403(request)
        if refused:
            return refused
        member = _member(request, pk)
        if member is None:
            return Response({'detail': 'Not someone at your branch.'}, status=404)
        profiles.remove_photo(member, by=request.user)
        return Response(profiles.card(member, _period(request)))
