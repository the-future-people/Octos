"""
The website's "Not sure what to ask for?" (23 Nov 2026): a visitor shows
Octos a photo, short video or GIF and watches it work out what it is and
whether Farhat can make it. No sign-in. Five looks a day per visitor,
because each one costs AI and search.

  POST /api/v1/sandbox/          files (up to 3 pictures, or 1 video or GIF) + note  -> {code}
  GET  /api/v1/sandbox/<code>/   progress, then the answer
"""
import hashlib
import uuid
from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.communications.models import SandboxCase
from apps.communications.services.sandbox import for_customer

LOOKS_A_DAY = 5
MAX_PICTURES = 3
PICTURE_BYTES = 10 * 1024 * 1024
VIDEO_BYTES = 25 * 1024 * 1024
PICTURES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
MOVING = {'image/gif', 'video/mp4', 'video/quicktime', 'video/webm', 'video/3gpp'}


def visitor(request):
    """A hash of the visitor's address: enough for a daily limit, never stored as the address."""
    ip = (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', ''))
    return hashlib.sha256(f'sandbox:{ip}'.encode()).hexdigest()[:40]


class SandboxStartView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        who = visitor(request)
        today = timezone.now() - timedelta(hours=24)
        if SandboxCase.objects.filter(visitor=who, source=SandboxCase.WEB, created_at__gte=today).count() >= LOOKS_A_DAY:
            return Response({'detail': "That's today's five looks. Ask us on WhatsApp and we'll help straight away."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        files = request.FILES.getlist('files')
        if not files:
            return Response({'detail': 'Add a photo, a short video or a GIF.'}, status=status.HTTP_400_BAD_REQUEST)
        moving = [f for f in files if (f.content_type or '').lower() in MOVING]
        still = [f for f in files if (f.content_type or '').lower() in PICTURES]
        if len(moving) + len(still) != len(files):
            return Response({'detail': 'Only photos (JPG, PNG), short videos (MP4) or GIFs.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if moving and (len(files) > 1):
            return Response({'detail': 'One video or GIF at a time, or up to 3 photos.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(still) > MAX_PICTURES:
            return Response({'detail': 'Up to 3 photos at a time.'}, status=status.HTTP_400_BAD_REQUEST)
        for f in files:
            limit = VIDEO_BYTES if f in moving else PICTURE_BYTES
            if f.size > limit:
                return Response({'detail': f'That file is too big (up to {limit // (1024 * 1024)} MB).'},
                                status=status.HTTP_400_BAD_REQUEST)
        stored = []
        for f in files:
            path = default_storage.save(f'sandbox/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}-{f.name[-60:]}',
                                        ContentFile(f.read()))
            stored.append({'path': path, 'mime': (f.content_type or '').lower(), 'name': f.name[-100:]})
        case = SandboxCase.objects.create(source=SandboxCase.WEB, visitor=who, files=stored,
                                          note=str(request.data.get('note') or '')[:500])
        from django.db import transaction

        from apps.communications.tasks import run_sandbox
        transaction.on_commit(lambda: run_sandbox.delay(case.pk))
        return Response({'code': case.code, 'looks_left': LOOKS_A_DAY - 1 - SandboxCase.objects.filter(
            visitor=who, source=SandboxCase.WEB, created_at__gte=today).exclude(pk=case.pk).count()},
            status=status.HTTP_201_CREATED)


class SandboxCaseView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, code):
        case = SandboxCase.objects.filter(code=str(code).upper(), source=SandboxCase.WEB).first()
        if case is None:
            return Response({'detail': 'No such look.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(for_customer(case))
