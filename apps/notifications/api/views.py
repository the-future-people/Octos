from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import Notification
from apps.notifications.api.serializers import NotificationSerializer
from apps.notifications.services import get_unread_count, mark_all_read


class NotificationListView(APIView):
    """
    GET /api/v1/notifications/
    Returns notifications for the authenticated user.
    Accepts:
      ?unread=true           — filter unread only
      ?display_mode=X        — filter by PASSIVE / INTERRUPTIVE
    Passive/default calls (bell dropdown) are capped at the latest 20.
    Interruptive-mode calls return all matches uncapped, since a
    reminder must never be silently pushed out by a slice limit.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user)

        if request.query_params.get('unread') == 'true':
            qs = qs.filter(is_read=False)

        display_mode = request.query_params.get('display_mode')
        if display_mode:
            qs = qs.filter(display_mode=display_mode)

        qs = qs.select_related('actor')
        if display_mode != 'INTERRUPTIVE':
            qs = qs[:20]

        serializer = NotificationSerializer(qs, many=True)
        return Response(serializer.data)


class UnreadCountView(APIView):
    """
    GET /api/v1/notifications/unread-count/
    Returns {"count": N}
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'count': get_unread_count(request.user)})


class MarkReadView(APIView):
    """
    POST /api/v1/notifications/<pk>/read/
    Marks a single notification as read.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            notif = Notification.objects.get(pk=pk, recipient=request.user)
        except Notification.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        notif.mark_read()
        return Response({'id': notif.pk, 'is_read': True})


class MarkAllReadView(APIView):
    """
    POST /api/v1/notifications/read-all/
    Marks all notifications as read for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        count = mark_all_read(request.user)
        return Response({'marked_read': count})