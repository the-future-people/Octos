from celery import shared_task


@shared_task
def close_stale():
    """Applications left unanswered 14 days after "Ask for more" close (daily)."""
    from apps.partners.services import review
    return review.close_stale()
