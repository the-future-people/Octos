from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
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
        qs = Conversation.objects.select_related(
            'branch', 'customer', 'assigned_to'
        ).all()
        branch_id = self.request.query_params.get('branch')
        channel = self.request.query_params.get('channel')
        status_param = self.request.query_params.get('status')
        assigned_to = self.request.query_params.get('assigned_to')

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
    queryset = Conversation.objects.select_related(
        'branch', 'customer', 'assigned_to'
    ).prefetch_related('messages', 'jobs').all()
    serializer_class = ConversationDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        obj = super().get_object()
        # Mark as read — reset unread count
        obj.unread_count = 0
        obj.save(update_fields=['unread_count'])
        return obj


class ConversationReplyView(APIView):
    """
    Reply to a conversation.
    POST /api/v1/communications/{id}/reply/
    Replying to an unclaimed conversation auto-claims it.
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

        message = Message.objects.create(
            conversation=conversation,
            direction=Message.OUTBOUND,
            channel=conversation.channel,
            sent_by=request.user,
            **serializer.validated_data
        )

        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class ConversationAssignView(APIView):
    """
    Assign or reassign a conversation to a staff member.
    POST /api/v1/communications/{id}/assign/
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
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        conversation.assigned_to = user
        conversation.save(update_fields=['assigned_to'])

        # Log system message
        Message.objects.create(
            conversation=conversation,
            direction=Message.OUTBOUND,
            channel=Message.SYSTEM,
            message_type=Message.NOTE,
            is_internal_note=True,
            body=f"Conversation assigned to {user.get_full_name()} by {request.user.get_full_name()}",
            sent_by=request.user
        )

        return Response({
            'success': True,
            'assigned_to': user.get_full_name(),
            'assigned_to_id': user.id,
        })


class ConversationResolveView(APIView):
    """
    Mark a conversation as resolved.
    POST /api/v1/communications/{id}/resolve/
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

        conversation.status = Conversation.RESOLVED
        conversation.save(update_fields=['status'])

        Message.objects.create(
            conversation=conversation,
            direction=Message.OUTBOUND,
            channel=Message.SYSTEM,
            message_type=Message.NOTE,
            is_internal_note=True,
            body=f"Conversation resolved by {request.user.get_full_name()}",
            sent_by=request.user
        )

        return Response({'success': True, 'status': 'RESOLVED'})


class ConversationLinkJobView(APIView):
    """
    Link a job to a conversation.
    POST /api/v1/communications/{id}/link-job/
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
        if not job_id:
            return Response(
                {'detail': 'job_id is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        conversation.jobs.add(job)

        return Response({
            'success': True,
            'job_number': job.job_number,
            'linked_to_conversation': conversation.id,
        })


class InboundWebhookView(APIView):
    """
    Stub endpoint for inbound messages from WhatsApp/Twilio.
    Will be wired to actual providers in the Communications phase.
    POST /api/v1/communications/webhook/inbound/
    """
    permission_classes = []  # Webhooks are unauthenticated — verified by signature

    def post(self, request):
        # TODO: verify webhook signature
        # TODO: parse provider payload
        # TODO: find or create conversation
        # TODO: create inbound Message record
        return Response({'status': 'received'}, status=status.HTTP_200_OK)