# apps/core/broadcast.py
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def broadcast_invalidation(branch_id: int, events: list[str]):
    """
    Broadcasts an invalidation signal to all WebSocket clients
    connected to the given branch room.

    Called from services after job creation, payment confirmation,
    job transition, sheet close, or customer registration.

    Args:
        branch_id: The branch whose clients should be notified.
        events:    List of React Query cache keys to invalidate.
                   e.g. ['paymentQueue', 'jobStats', 'todaySummary']
    """
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'branch_{branch_id}',
            {
                'type':   'branch.invalidate',
                'events': events,
            }
        )
    except Exception:
        # Broadcasting is non-critical — never let a failed signal
        # break the actual business operation that triggered it
        pass