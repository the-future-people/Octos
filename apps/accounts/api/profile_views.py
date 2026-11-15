"""
Staff profiles (15 Nov 2026). See accounts/profiles.py.

  GET   /api/v1/accounts/profile/?period=week     your own card and numbers
  PATCH /api/v1/accounts/profile/                 {phone}
  POST  /api/v1/accounts/profile/photo/           multipart "photo"
  DELETE /api/v1/accounts/profile/photo/

  GET   /api/v1/accounts/staff/?period=week       the branch's cards (Branch Manager)
  PATCH /api/v1/accounts/staff/<id>/              {phone} (Branch Manager, his branch)
  POST  /api/v1/accounts/staff/<id>/photo/        multipart "photo" (Branch Manager, his branch)
  DELETE /api/v1/accounts/staff/<id>/photo/
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
        try:
            profiles.set_phone(request.user, request.data.get('phone', ''))
        except profiles.ProfileRefused as exc:
            return _refused(exc)
        return Response(profiles.card(request.user, _period(request)))


class ProfilePhotoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.FILES.get('photo')
        if upload is None:
            return Response({'detail': 'Choose a photo first.'}, status=400)
        try:
            profiles.set_photo(request.user, upload)
        except profiles.ProfileRefused as exc:
            return _refused(exc)
        return Response(profiles.card(request.user, _period(request)))

    def delete(self, request):
        profiles.remove_photo(request.user)
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
        return Response({'period': period, 'staff': cards, 'counts': counts, 'on': on})


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
            profiles.set_phone(member, request.data.get('phone', ''), by=request.user)
        except profiles.ProfileRefused as exc:
            return _refused(exc)
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
