"""
PUT    /api/v1/jobs/services/<id>/photo/   a new photo for a service
DELETE /api/v1/jobs/services/<id>/photo/   take the photo off

From the catalogue's side pane (17 Nov 2026). Before this, a photo could
only be set when a service was created.

The photo goes to the public catalogue bucket (apps/jobs/storage.py), the
same one the website and app read, so a change shows everywhere. The
people who set company prices change photos too: a Super Admin, and the
managers while MANAGERS_SET_COMPANY_PRICES is on. The old photo is removed
from the bucket once the new one is saved, so it doesn't pile up.
"""
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.api.serializers import ServiceSerializer
from apps.jobs.models import Service

MAX_BYTES = 5 * 1024 * 1024
KINDS = ('image/jpeg', 'image/png', 'image/webp')


def _may_change(user):
    from apps.jobs.api.views import _managers_set_company_prices

    role = getattr(getattr(user, 'role', None), 'name', '')
    return role == 'SUPER_ADMIN' or _managers_set_company_prices(role)


def _forget(name, storage):
    """Remove an old photo from the bucket; a miss is not worth failing over."""
    if not name:
        return
    try:
        storage.delete(name)
    except Exception:
        pass


class ServicePhotoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _service(self, request, pk):
        if not _may_change(request.user):
            return None, Response({'detail': 'Only a manager can change catalogue photos.'},
                                  status=status.HTTP_403_FORBIDDEN)
        service = Service.objects.filter(pk=pk).first()
        if service is None:
            return None, Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return service, None

    def put(self, request, pk):
        service, refused = self._service(request, pk)
        if refused:
            return refused

        photo = request.FILES.get('image')
        if photo is None:
            return Response({'detail': 'Choose a photo first.'}, status=status.HTTP_400_BAD_REQUEST)
        if photo.content_type not in KINDS:
            return Response({'detail': 'Use a JPG, PNG or WebP photo.'}, status=status.HTTP_400_BAD_REQUEST)
        if photo.size > MAX_BYTES:
            return Response({'detail': 'That photo is over 5 MB. Use a smaller one.'},
                            status=status.HTTP_400_BAD_REQUEST)

        old = service.image.name if service.image else ''
        service.image = photo          # saving clears the services list cache (models/service.py)
        service.save(update_fields=['image', 'updated_at'])
        if old and old != service.image.name:
            _forget(old, service.image.storage)
        return Response(ServiceSerializer(service, context={'request': request}).data)

    def delete(self, request, pk):
        service, refused = self._service(request, pk)
        if refused:
            return refused
        if service.image:
            old, storage = service.image.name, service.image.storage
            service.image = None
            service.save(update_fields=['image', 'updated_at'])
            _forget(old, storage)
        return Response(ServiceSerializer(service, context={'request': request}).data)
