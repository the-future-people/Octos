from celery import shared_task
import logging
logger = logging.getLogger(__name__)

@shared_task
def expire_drafts():
    from django.core.management import call_command
    call_command('expire_drafts')


@shared_task
def expire_quotes():
    """
    Expire quotes past their 21 days, and tell the manager who issued each
    one. A quote that dies unanswered is a lost sale, and finding out when
    the customer calls in week four is finding out too late.
    """
    from django.utils import timezone
    from apps.jobs.models import ProformaInvoice
    from apps.jobs.services.quote_engine import QuoteEngine
    from apps.notifications.services import notify

    # Collected before expiring, since the update changes the status these
    # rows are selected by.
    stale = list(
        ProformaInvoice.objects
        .select_related('issued_by', 'customer')
        .filter(
            status=ProformaInvoice.Status.ISSUED,
            valid_until__lt=timezone.localdate(),
        )
    )

    count = QuoteEngine.expire_stale_quotes()

    for q in stale:
        if not q.issued_by:
            continue
        try:
            notify(
                recipient = q.issued_by,
                verb      = 'quote_expired',
                message   = (
                    f"{q.proforma_number} for {q.issued_to} "
                    f"(GHS {q.total}) expired without an answer."
                ),
                link      = '/portal/quotes/',
            )
        except Exception:
            logger.exception('Failed to notify on expired quote %s', q.pk)

    logger.info('expire_quotes: expired %s quote(s)', count)
    return count


# Days after issue at which the issuing manager is nudged. The last is the
# three-days-left warning — after 21 days the quote is gone and a new one
# must be raised at current prices.
QUOTE_REMINDER_DAYS = (3, 10, 18)


@shared_task
def remind_open_quotes():
    """
    Nudge the manager who issued a quote that has gone quiet.

    Deliberately internal only. Chasing the customer directly needs
    WhatsApp, which is not integrated yet, and an email nobody reads is
    worse than a manager who remembers to call.
    """
    from django.utils import timezone
    from apps.jobs.models import ProformaInvoice
    from apps.notifications.services import notify

    today = timezone.localdate()
    sent  = 0

    open_quotes = (
        ProformaInvoice.objects
        .select_related('issued_by', 'customer')
        .filter(status=ProformaInvoice.Status.ISSUED, issued_at__isnull=False)
    )

    for q in open_quotes:
        age = (today - q.issued_at.date()).days
        if age not in QUOTE_REMINDER_DAYS:
            continue
        # One nudge per day at most, however many times this runs.
        if q.last_reminder_at and q.last_reminder_at.date() == today:
            continue
        if not q.issued_by:
            continue

        days_left = (q.valid_until - today).days if q.valid_until else None
        if days_left is not None and days_left <= 3:
            body = (
                f"{q.proforma_number} for {q.issued_to} expires in "
                f"{days_left} day{'s' if days_left != 1 else ''}. "
                f"GHS {q.total} still unanswered."
            )
        else:
            body = (
                f"{q.proforma_number} for {q.issued_to} (GHS {q.total}) "
                f"has been out {age} days with no answer."
            )

        try:
            notify(
                recipient = q.issued_by,
                verb      = 'quote_followup',
                message   = body,
                link      = '/portal/quotes/',
            )
            q.last_reminder_at = timezone.now()
            q.save(update_fields=['last_reminder_at', 'updated_at'])
            sent += 1
        except Exception:
            logger.exception('Failed to send quote reminder for %s', q.pk)

    logger.info('remind_open_quotes: sent %s reminder(s)', sent)
    return sent