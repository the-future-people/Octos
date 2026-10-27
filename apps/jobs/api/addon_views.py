"""
Finishing priced as it is chosen at the counter.

POST /api/v1/jobs/addons/quote/
    { service, quantity, pages, specifications, addons }

The same function the app prices finishing with (price_addons), so
lamination is counted by the sheet, binding by the copy with its ring
chosen from the sheets, and an envelope one per copy or one for all,
wherever the job is taken. Job creation prices it again: this is only
what the screen shows while the CSE chooses.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class AddonQuoteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.jobs.models import Service
        from apps.jobs.services.availability import price_addons

        service = Service.objects.filter(pk=request.data.get('service'), is_active=True).first()
        if service is None:
            return Response({'detail': 'That service is not available.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            quantity = max(1, int(request.data.get('quantity') or 1))
            pages = max(1, int(request.data.get('pages') or 1))
        except (TypeError, ValueError):
            return Response({'detail': 'Check the quantity and pages.'}, status=status.HTTP_400_BAD_REQUEST)
        specs = {**(request.data.get('specifications') or {}), 'pages': pages}
        priced, total, problem = price_addons(service, request.data.get('addons') or [], quantity, specs)
        if problem:
            return Response({'detail': problem}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'addons': priced, 'total': f'{total:.2f}'})