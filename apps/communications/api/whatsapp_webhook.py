"""
GET/POST /api/v1/communications/webhook/whatsapp/

Meta's webhook for Farhat's WhatsApp number. Modelled on the Paystack
webhook: the signature is checked against the raw body, the delivery is
stored, and Meta gets its answer quickly.
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.communications.models import WhatsAppEvent
from apps.communications.services import whatsapp_inbound

logger = logging.getLogger(__name__)


class WhatsAppWebhookView(APIView):
    """
    GET   Meta's one-time verification. Echoes hub.challenge when the
          verify token matches, as plain text: a DRF Response would
          render it as JSON, quotes included, and Meta would refuse it.

    POST  Messages and delivery statuses. In order:

      the signature  X-Hub-Signature-256, HMAC-SHA256 of the raw body
                     with the app secret. Read from request.body before
                     anything touches request.data, which would consume
                     the stream.
      the store      the delivery is saved as it arrived, before any
                     parsing, so a parser bug loses nothing.
      the answer     200 once stored, even if processing failed. Meta
                     retries anything else, and retrying into the same
                     bug achieves nothing; the error is on the event,
                     and the event can be replayed.

    No authentication and no throttle. Meta sends no credentials, and
    a burst of delivery receipts would trip the anonymous limit and be
    retried into it. The signature is what keeps strangers out.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        token = settings.WHATSAPP_VERIFY_TOKEN
        if not token:
            logger.error('WhatsApp verification refused: WHATSAPP_VERIFY_TOKEN is not set')
            return HttpResponse(status=status.HTTP_403_FORBIDDEN)

        mode = request.query_params.get('hub.mode', '')
        given = request.query_params.get('hub.verify_token', '')
        challenge = request.query_params.get('hub.challenge', '')

        if mode == 'subscribe' and hmac.compare_digest(given.encode(), token.encode()):
            logger.info('WhatsApp webhook verified')
            return HttpResponse(challenge, content_type='text/plain')

        logger.warning('WhatsApp verification refused: mode %r, wrong token', mode)
        return HttpResponse(status=status.HTTP_403_FORBIDDEN)

    def post(self, request):
        raw = request.body
        if not self._signed(raw, request.headers.get('X-Hub-Signature-256', '')):
            return Response({'detail': 'Bad signature.'},
                            status=status.HTTP_401_UNAUTHORIZED)

        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            logger.warning('WhatsApp webhook with an unreadable body')
            return Response({'detail': 'Unreadable body.'},
                            status=status.HTTP_400_BAD_REQUEST)

        event = WhatsAppEvent.objects.create(payload=payload)
        try:
            whatsapp_inbound.process(event)
        except Exception as exc:
            logger.exception('WhatsApp event %s could not be processed', event.pk)
            event.error = repr(exc)
            event.save(update_fields=['error'])

        return Response({'status': 'received'})

    @staticmethod
    def _signed(raw, given):
        """
        'sha256=' + HMAC-SHA256 of the raw body with the app secret,
        compared in constant time. A missing secret refuses everything
        and says so in the log, so it cannot pass as a quiet run of bad
        signatures.
        """
        secret = settings.WHATSAPP_APP_SECRET
        if not secret:
            logger.error('WhatsApp webhook refused: WHATSAPP_APP_SECRET is not set')
            return False
        if not given:
            logger.warning('WhatsApp webhook with no signature')
            return False
        expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected.encode(), given.encode()):
            logger.warning('WhatsApp webhook with a bad signature')
            return False
        return True