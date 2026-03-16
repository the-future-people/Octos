from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.communications.models import Conversation, Message
from apps.accounts.models import CustomUser
from .serializers import (
    ConversationListSerializer, ConversationDetailSerializer,
    MessageSerializer, MessageCreateSerializer, ConversationAssignSerializer
)


class ConversationListView(generics.ListAPIView):
    serializer_class = ConversationListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['contact_phone', 'contact_email', 'contact_name']

    def get_queryset(self):
        user = self.request.user
        qs = Conversation.objects.select_related(
            'branch', 'customer', 'assigned_to'
        )

        # Scope to user's branch by default
        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)

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
        user = self.request.user
        qs = Conversation.objects.select_related(
            'branch', 'customer', 'assigned_to'
        ).prefetch_related('messages', 'jobs')

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)

        return qs

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
    Replying to an unclaimed conversation auto-assigns it to the replying user.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            conversation = Conversation.objects.get(pk=pk)
        except Conversation.DoesNotExist:
            return Response(
                {'detail': 'Conversation not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = MessageCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Auto-claim if unclaimed
        if not conversation.assigned_to:
            conversation.assigned_to = request.user
            conversation.save(update_fields=['assigned_to'])

        # Use SYSTEM channel for internal notes, otherwise use conversation channel
        is_note = serializer.validated_data.get('is_internal_note', False)
        channel = Message.SYSTEM if is_note else conversation.channel

        message = Message.objects.create(
            conversation=conversation,
            direction=Message.OUTBOUND,
            channel=channel,
            sent_by=request.user,
            **serializer.validated_data
        )

        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class ConversationAssignView(APIView):
    """
    POST /api/v1/communications/<id>/assign/
    Body: { user_id }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            conversation = Conversation.objects.get(pk=pk)
        except Conversation.DoesNotExist:
            return Response(
                {'detail': 'Conversation not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

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
        try:
            conversation = Conversation.objects.get(pk=pk)
        except Conversation.DoesNotExist:
            return Response(
                {'detail': 'Conversation not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

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
        try:
            conversation = Conversation.objects.get(pk=pk)
        except Conversation.DoesNotExist:
            return Response(
                {'detail': 'Conversation not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

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


class InboundWebhookView(APIView):
    """
    POST /api/v1/communications/webhook/inbound/
    Stub — will be wired to WhatsApp/Twilio providers in the Communications phase.
    """
    permission_classes = []  # Unauthenticated — verified by provider signature

    def post(self, request):
        # TODO: verify webhook signature
        # TODO: parse provider payload (WhatsApp / Twilio)
        # TODO: find or create Conversation
        # TODO: create inbound Message record
        return Response({'status': 'received'}, status=status.HTTP_200_OK)