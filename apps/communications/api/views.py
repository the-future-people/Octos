from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.communications.models import Conversation, Message
from apps.communications.services.access import visible_conversations
from apps.accounts.models import CustomUser
from .serializers import (
    ConversationListSerializer, ConversationDetailSerializer,
    MessageSerializer, MessageCreateSerializer, ConversationAssignSerializer
)

# What staff are told when WhatsApp's 24-hour window is shut. Plain words:
# staff don't need to know what a template is, only when it will work again.
WINDOW_CLOSED = (
    "This customer hasn't written to us in the last 24 hours, so WhatsApp "
    "won't deliver a normal message. It will work again as soon as they write."
)


def _visible(request, pk):
    """The conversation, if this user may see it; None if not, or if it doesn't exist."""
    return visible_conversations(request.user).filter(pk=pk).first()


def _not_found():
    return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)


class ConversationListView(generics.ListAPIView):
    serializer_class = ConversationListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['contact_phone', 'contact_email', 'contact_name']

    def get_queryset(self):
        # The user's branch plus every company (WhatsApp) conversation;
        # everything for a user with no branch. See services/access.py.
        qs = visible_conversations(self.request.user).select_related(
            'branch', 'customer', 'assigned_to'
        )

        # Optional query param overrides (for managers with multi-branch access)
        branch_id    = self.request.query_params.get('branch')
        channel      = self.request.query_params.get('channel')
        status_param = self.request.query_params.get('status')
        assigned_to  = self.request.query_params.get('assigned_to')

        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if channel:
            qs = qs.filter(channel=channel)
        if status_param:
            qs = qs.filter(status=status_param)
        if assigned_to:
            qs = qs.filter(assigned_to_id=assigned_to)

        return qs


class ConversationDetailView(generics.RetrieveAPIView):
    serializer_class = ConversationDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return visible_conversations(self.request.user).select_related(
            'branch', 'customer', 'assigned_to'
        ).prefetch_related('messages', 'jobs')

    def get_object(self):
        obj = super().get_object()
        # Reset unread count when opened
        obj.unread_count = 0
        obj.save(update_fields=['unread_count'])
        return obj


class ConversationReplyView(APIView):
    """
    POST /api/v1/communications/<id>/reply/
    Body: { body, message_type?, is_internal_note? }

    A reply on a WhatsApp conversation is really sent: through
    whatsapp_outbound.send_text, which checks the 24-hour window, records
    the message as QUEUED and has the worker deliver it. Its status then
    follows Meta's receipts. A shut window is refused with a plain reason;
    nothing is saved that wasn't sent.

    Internal notes, and replies on other channels, are recorded as before.
    Replying to an unclaimed conversation claims it for the replying user,
    once the reply has actually gone.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        serializer = MessageCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        is_note = data.get('is_internal_note', False)

        if conversation.channel == Conversation.WHATSAPP and not is_note:
            from apps.communications.services import whatsapp_outbound
            try:
                message = whatsapp_outbound.send_text(
                    conversation, data.get('body', ''), sent_by=request.user,
                )
            except whatsapp_outbound.WindowClosed:
                return Response({'detail': WINDOW_CLOSED}, status=status.HTTP_400_BAD_REQUEST)
            except ValueError as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Use SYSTEM channel for internal notes, otherwise the conversation's channel
            channel = Message.SYSTEM if is_note else conversation.channel
            message = Message.objects.create(
                conversation=conversation,
                direction=Message.OUTBOUND,
                channel=channel,
                sent_by=request.user,
                **data
            )

        # Auto-claim if unclaimed, now that something was actually sent or noted
        if not conversation.assigned_to:
            conversation.assigned_to = request.user
            conversation.save(update_fields=['assigned_to'])

        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class ConversationAssignView(APIView):
    """
    POST /api/v1/communications/<id>/assign/
    Body: { user_id }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        serializer = ConversationAssignSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = CustomUser.objects.get(pk=serializer.validated_data['user_id'])
        except CustomUser.DoesNotExist:
            return Response(
                {'detail': 'User not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        previous = conversation.assigned_to
        conversation.assigned_to = user
        conversation.save(update_fields=['assigned_to'])

        # System note — only log if it's a reassignment
        note = (
            f"Reassigned from {previous.full_name} to {user.full_name}"
            if previous
            else f"Assigned to {user.full_name} by {request.user.full_name}"
        )
        Message.objects.create(
            conversation=conversation,
            direction=Message.OUTBOUND,
            channel=Message.SYSTEM,
            message_type=Message.NOTE,
            is_internal_note=True,
            body=note,
            sent_by=request.user,
        )

        return Response({
            'success'        : True,
            'assigned_to'    : user.full_name,
            'assigned_to_id' : user.id,
        })


class ConversationResolveView(APIView):
    """
    POST /api/v1/communications/<id>/resolve/
    Marks conversation as RESOLVED and logs a system note.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        if conversation.status == Conversation.RESOLVED:
            return Response(
                {'detail': 'Conversation is already resolved.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        conversation.status = Conversation.RESOLVED
        conversation.save(update_fields=['status'])

        Message.objects.create(
            conversation=conversation,
            direction=Message.OUTBOUND,
            channel=Message.SYSTEM,
            message_type=Message.NOTE,
            is_internal_note=True,
            body=f"Conversation resolved by {request.user.full_name}",
            sent_by=request.user,
        )

        return Response({'success': True, 'status': 'RESOLVED'})


class ConversationLinkJobView(APIView):
    """
    POST /api/v1/communications/<id>/link-job/
    Body: { job_id }          — links job to conversation
    Body: { job_id: null }    — clears all linked jobs (unlink)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        job_id = request.data.get('job_id')

        # Unlink — job_id explicitly null
        if job_id is None:
            conversation.jobs.clear()
            return Response({'success': True, 'linked': False})

        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            return Response(
                {'detail': 'Job not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        conversation.jobs.add(job)

        return Response({
            'success'               : True,
            'linked'                : True,
            'job_id'                : job.id,
            'linked_to_conversation': conversation.id,
        })