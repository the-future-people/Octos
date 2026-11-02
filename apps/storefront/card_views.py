"""
GET y/<code>/ — a customer's year-end card, by its private code.

Public by design, like the tracking link: the code is the key, and it
opens one card and nothing else.
"""

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


class YearCardView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

    def get(self, request, code):
        from apps.storefront.models import YearCard
        from apps.storefront.services.year_card import card_page

        card = YearCard.objects.filter(code=(code or '').upper()[:10]).first()
        if card is None:
            return Response({'detail': 'This card was not found.'}, status=404)
        if card.opened_at is None:
            YearCard.objects.filter(pk=card.pk, opened_at__isnull=True).update(opened_at=timezone.now())
        return Response(card_page(card))
