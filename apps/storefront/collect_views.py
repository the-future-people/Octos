"""
The counter's side of collection, for signed-in staff.

GET  collect/?phone=&pin=   or   collect/?qr=PO:ORD-…:1234
POST collect/hand-over/  { order_number, pin, collected_by? }
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.storefront.services.collection import CollectRefused, find, hand_over, summary


class CollectLookupView(APIView):
    permission_classes = [IsAuthenticated]
    # A few tries a minute: enough for a typo, slow for guessing PINs.
    throttle_classes = [UserRateThrottle]

    def get(self, request):
        try:
            orders = find(
                phone=request.query_params.get('phone', ''),
                pin=request.query_params.get('pin', ''),
                qr=request.query_params.get('qr', ''),
            )
        except CollectRefused as refused:
            return Response({'detail': str(refused)}, status=status.HTTP_404_NOT_FOUND)
        return Response({'orders': [summary(o) for o in orders]})


class CollectHandOverView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            order = hand_over(
                request.data.get('order_number', ''),
                request.data.get('pin', ''),
                actor=request.user,
                collected_by=request.data.get('collected_by', ''),
            )
        except CollectRefused as refused:
            return Response({'detail': str(refused)}, status=status.HTTP_409_CONFLICT)
        return Response({'collected': True, 'order_number': order.order_number})
