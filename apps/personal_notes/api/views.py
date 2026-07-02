from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.personal_notes.models import PersonalNote, NotePin, TaskCheckpoint
from apps.personal_notes.services import generate_checkpoints, acknowledge_checkpoint, complete_task
from apps.core.throttling import PinVerifyRateThrottle
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
        note = serializer.save(owner=self.request.user)
        if note.note_type == 'TASK' and note.due_date:
            generate_checkpoints(note)


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

    def perform_update(self, serializer):
        old_due_date = serializer.instance.due_date
        old_type     = serializer.instance.note_type
        note = serializer.save()
        # Regenerate checkpoints if this just became a task, or due_date changed
        if note.note_type == 'TASK' and note.due_date:
            if old_type != 'TASK' or old_due_date != note.due_date:
                generate_checkpoints(note)
        elif note.note_type == 'NOTE':
            # Converted back to a plain note — clear any stale checkpoints
            note.checkpoints.all().delete()


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
    Returns { "valid": true|false }.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes   = [PinVerifyRateThrottle]

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
    Returns:
      - plain notes with reminder_at in the past, not dismissed
      - task checkpoints that are due, not yet acknowledged
    Both surfaced together so the frontend can show whichever fires first.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        from .serializers import TaskCheckpointSerializer

        now = timezone.now()

        due_notes = PersonalNote.objects.filter(
            owner               = request.user,
            note_type           = 'NOTE',
            reminder_at__lte    = now,
            reminder_dismissed  = False,
        ).order_by('reminder_at')

        due_checkpoints = TaskCheckpoint.objects.filter(
            note__owner   = request.user,
            note__status  = 'ACTIVE',
            scheduled_at__lte = now,
            acknowledged  = False,
        ).select_related('note').order_by('scheduled_at')

        checkpoint_data = []
        for cp in due_checkpoints:
            data = TaskCheckpointSerializer(cp).data
            data['note'] = PersonalNoteSerializer(cp.note).data
            checkpoint_data.append(data)

        return Response({
            'notes':       PersonalNoteSerializer(due_notes, many=True).data,
            'checkpoints': checkpoint_data,
        })


class DismissReminderView(APIView):
    """
    POST /api/v1/personal-notes/<id>/dismiss-reminder/
    Marks a plain note's reminder as seen.
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


class AcknowledgeCheckpointView(APIView):
    """
    POST /api/v1/personal-notes/checkpoints/<id>/acknowledge/
    'Still working on it' — acknowledges this checkpoint only.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            checkpoint = TaskCheckpoint.objects.get(pk=pk, note__owner=request.user)
        except TaskCheckpoint.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        acknowledge_checkpoint(checkpoint)
        return Response({'detail': 'Acknowledged.'})


class CompleteTaskView(APIView):
    """
    POST /api/v1/personal-notes/<id>/complete/
    'Mark complete' — closes out the task regardless of which
    checkpoint triggered it. Acknowledges all remaining checkpoints.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            note = PersonalNote.objects.get(pk=pk, owner=request.user)
        except PersonalNote.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        complete_task(note)
        return Response(PersonalNoteSerializer(note).data)