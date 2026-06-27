from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.personal_notes.models import PersonalNote, NotePin
from .serializers import PersonalNoteSerializer, SetPinSerializer, VerifyPinSerializer


# ── Notes CRUD — strictly owner-scoped, no exceptions ───────────────────────

class PersonalNoteListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/personal-notes/         — list current user's notes only
    POST /api/v1/personal-notes/         — create a note for current user
    """
    serializer_class   = PersonalNoteSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = None

    def get_queryset(self):
        return PersonalNote.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class PersonalNoteDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/v1/personal-notes/<id>/
    Owner-scoped — a note belonging to another user 404s, never 403s,
    so existence isn't leaked either.
    """
    serializer_class   = PersonalNoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PersonalNote.objects.filter(owner=self.request.user)


# ── PIN management ────────────────────────────────────────────────────────────

class PinStatusView(APIView):
    """
    GET /api/v1/personal-notes/pin/status/
    Tells frontend whether the current user has set a PIN yet.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        has_pin = NotePin.objects.filter(owner=request.user).exists()
        return Response({'has_pin': has_pin})


class SetPinView(APIView):
    """
    POST /api/v1/personal-notes/pin/set/
    Body: { "pin": "1234" }
    Creates the PIN if none exists. If one already exists, this
    endpoint refuses — use a separate reset flow (built later).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if NotePin.objects.filter(owner=request.user).exists():
            return Response(
                {'detail': 'PIN already set. Use reset flow to change it.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SetPinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        note_pin = NotePin(owner=request.user)
        note_pin.set_pin(serializer.validated_data['pin'])
        note_pin.save()

        return Response({'detail': 'PIN set successfully.'}, status=status.HTTP_201_CREATED)


class VerifyPinView(APIView):
    """
    POST /api/v1/personal-notes/pin/verify/
    Body: { "pin": "1234" }
    Returns { "valid": true|false }. Never reveals whether a PIN
    exists vs is wrong — same response shape either way upstream
    of this (frontend checks pin-status first).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = VerifyPinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            note_pin = NotePin.objects.get(owner=request.user)
        except NotePin.DoesNotExist:
            return Response({'valid': False}, status=status.HTTP_200_OK)

        is_valid = note_pin.check_pin(serializer.validated_data['pin'])
        return Response({'valid': is_valid})


# ── Reminders ──────────────────────────────────────────────────────────────

class DueRemindersView(APIView):
    """
    GET /api/v1/personal-notes/due-reminders/
    Returns any notes with a reminder_at in the past that haven't
    been dismissed yet. Used by the global portal-wide reminder check.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone

        due = PersonalNote.objects.filter(
            owner               = request.user,
            reminder_at__lte    = timezone.now(),
            reminder_dismissed  = False,
        ).order_by('reminder_at')

        return Response(PersonalNoteSerializer(due, many=True).data)


class DismissReminderView(APIView):
    """
    POST /api/v1/personal-notes/<id>/dismiss-reminder/
    Marks a reminder as seen so it stops firing the full-screen modal.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            note = PersonalNote.objects.get(pk=pk, owner=request.user)
        except PersonalNote.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        note.reminder_dismissed = True
        note.save(update_fields=['reminder_dismissed'])
        return Response({'detail': 'Dismissed.'})