"""
WhatsApp's 24-hour window, in one place.

A customer's message opens a window: for 24 hours after it, a business
may send them anything. Outside it, only approved templates. Every rule
in Octos that depends on the window asks here, and nowhere else.

Two safety notes:

  We time the window from when the message reached us, a few seconds
  after the customer sent it. So it is treated as closing 5 minutes
  early, rather than sending in the last seconds and being refused.

  Meta has the final word. If it refuses a message as outside the
  window (error 131047), the sender treats the window as closed,
  whatever this file thought.
"""
from datetime import timedelta

from django.utils import timezone

from apps.communications.models import Message

WINDOW = timedelta(hours=24)
MARGIN = timedelta(minutes=5)


def last_inbound_at(conversation):
    """When the customer last wrote on WhatsApp, or None if never."""
    return (
        conversation.messages
        .filter(direction=Message.INBOUND, channel=Message.WHATSAPP)
        .order_by('-created_at')
        .values_list('created_at', flat=True)
        .first()
    )


def window_closes_at(conversation):
    """When free text stops being allowed, or None if it never was."""
    last = last_inbound_at(conversation)
    return last + WINDOW - MARGIN if last else None


def window_open(conversation, now=None):
    closes = window_closes_at(conversation)
    return closes is not None and (now or timezone.now()) < closes