"""
A job's complete file, for the BM's job page (13 Nov 2026).

One request gathers what the page shows: who it is for, who recorded it and
when, the type and where it stands, the items (item_lines, as on receipts),
every payment and its receipt (straight from the job: never another job's),
and the history merged in time order from the status logs, the receipts, the
spine, and the WhatsApp chat it came from, each with who and when.
"""
from datetime import timedelta

from django.utils import timezone

PHRASES = {
    ('PAYMENT', 'DEPOSIT_PAID'): 'Deposit paid',
    ('PAYMENT', 'SETTLED'): 'Paid in full',
    ('PAYMENT', 'UNPAID'): 'Marked unpaid',
    ('WORK', 'RECEIVED'): 'Received for production',
    ('WORK', 'IN_PRODUCTION'): 'Sent to production',
    ('WORK', 'FINISHING'): 'Finishing',
    ('WORK', 'QUALITY_CHECK'): 'Quality check',
    ('WORK', 'DONE'): 'Ready for collection',
    ('HANDOVER', 'AWAITING_COLLECTION'): 'Awaiting collection',
    ('HANDOVER', 'HANDED_OVER'): 'Handed over',
}
STATE_WORDS = {
    'UNPAID': 'Unpaid', 'DEPOSIT_PAID': 'Deposit paid', 'SETTLED': 'Paid in full',
    'RECEIVED': 'Received', 'IN_PRODUCTION': 'In production', 'FINISHING': 'Finishing',
    'QUALITY_CHECK': 'Quality check', 'DONE': 'Done',
    'AWAITING_COLLECTION': 'Awaiting collection', 'HANDED_OVER': 'Handed over',
    'OUT_FOR_DELIVERY': 'Out for delivery',
}
# Spine kinds that only mirror a status log: the log already tells it, with its actor.
MIRRORS = {'job.status_changed', 'job.deposit_paid', 'job.paid', 'job.ready', 'job.collected',
           'job.cancelled', 'job.halted', 'job.resumed', 'job.created'}
SPINE_TITLES = {
    'job.linked': 'Linked to the WhatsApp chat',
    'job.pickup_reminded': 'Reminded to collect',
    'job.feedback_nudged': 'Nudged about the design sample',
    'payment.succeeded': 'Paid online',
    'payment.link_sent': 'Payment link sent',
    'quote.given': 'Quote given',
}


def humanise(code):
    return (code or '').replace('_', ' ').strip().capitalize()


def phrase(axis, to_status):
    """A status log in words: 'Deposit paid', 'Sent to production'..."""
    if axis == 'RECORD':
        return 'Record updated'
    return PHRASES.get((axis, to_status)) or humanise(to_status)


def payment_label(index, count, settled_by_one):
    """Which payment this is: one paid in full, or a deposit then a balance."""
    if count == 1:
        return 'Paid in full' if settled_by_one else 'Payment'
    return 'Deposit' if index == 0 else ('Balance' if index == count - 1 else 'Part payment')


def entry(at, title, detail='', by='', tone='ink'):
    return {'at': at, 'title': title, 'detail': detail, 'by': by, 'tone': tone}


def _name(user):
    return getattr(user, 'full_name', '') or getattr(user, 'email', '') or ''


def build(job, now=None):
    from apps.communications.models import Conversation
    from apps.finance.models import Receipt
    from apps.jobs.models import Job, JobStatusLog
    from apps.jobs.services.item_lines import describe_job
    from apps.jobs.services.labels import contact_phone, for_whom, recorded_by
    from apps.spine.models import Event

    now = now or timezone.now()
    who, from_chat = for_whom(job)
    conversation = Conversation.objects.filter(jobs=job).first()
    others = (Job.objects.filter(customer=job.customer).count() if job.customer_id
              else (conversation.jobs.count() if conversation else 1))

    logs = list(JobStatusLog.objects.filter(job=job).select_related('actor').order_by('transitioned_at'))
    done_at = next((l.transitioned_at for l in reversed(logs) if l.axis == 'WORK' and l.to_status == 'DONE'), None)

    receipts = list(Receipt.objects.filter(job=job, is_void=False).select_related('cashier').order_by('created_at'))
    settled = job.payment_state == 'SETTLED'
    payments = []
    for i, r in enumerate(receipts):
        payments.append({
            'id': r.pk, 'receipt_number': r.receipt_number,
            'label': payment_label(i, len(receipts), settled),
            'method': r.payment_method,
            'method_label': ('Card (POS)' if r.payment_method == 'POS'
                             else 'Online (Paystack)' if 'online' in r.get_payment_method_display().lower()
                             else r.get_payment_method_display()),
            'amount': f'{r.amount_paid or 0:.2f}',
            'reference': getattr(r, 'momo_reference', '') or getattr(r, 'pos_approval_code', '') or '',
            'by': _name(r.cashier), 'at': r.created_at,
            'whatsapp_sent_at': r.whatsapp_sent_at,
        })

    history = [entry(job.created_at, 'Job recorded',
                     f"{humanise(job.job_type)} · came in by {humanise(job.intake_channel) or 'the counter'}",
                     recorded_by(job))]
    for l in logs:
        if l.axis not in ('PAYMENT', 'WORK', 'HANDOVER', 'RECORD'):
            continue
        tone = {'PAYMENT': 'money', 'WORK': 'work', 'HANDOVER': 'done', 'RECORD': 'ink'}[l.axis]
        history.append(entry(l.transitioned_at, phrase(l.axis, l.to_status), l.notes or '', _name(l.actor), tone))
    for p in payments:
        ref = f" · Ref {p['reference']}" if p['reference'] else ''
        # "paid online (Paystack)", not "by Paid Online" (13 Nov 2026).
        online = 'online' in (p['method_label'] or '').lower()
        how = 'paid online (Paystack)' if online else f"by {p['method_label']}"
        history.append(entry(p['at'], f"{p['label']}: GHS {p['amount']} {how}",
                             f"Receipt {p['receipt_number']}{ref}", p['by'], 'money'))
        if p['whatsapp_sent_at']:
            history.append(entry(p['whatsapp_sent_at'], 'Receipt sent on WhatsApp', p['receipt_number'], '', 'chat'))
    for e in Event.objects.filter(job=job).exclude(kind__in=MIRRORS).select_related('actor_user'):
        if e.kind in SPINE_TITLES:
            history.append(entry(e.occurred_at, SPINE_TITLES[e.kind], e.reason, _name(e.actor_user), 'chat'))

    if conversation is not None:
        # How it began: the chat in the hours before the job was recorded.
        before = Event.objects.filter(conversation=conversation, occurred_at__lte=job.created_at,
                                      occurred_at__gte=job.created_at - timedelta(hours=12)).select_related('actor_user')
        first_msg = before.filter(kind='message.received').order_by('occurred_at').first()
        if first_msg:
            history.append(entry(first_msg.occurred_at, 'Chat started on WhatsApp', who, '', 'chat'))
        qr = before.filter(kind='presence.counter').order_by('occurred_at').first()
        if qr:
            history.append(entry(qr.occurred_at, 'Scanned the counter QR', '', '', 'chat'))
        files = before.filter(kind='file.received').order_by('occurred_at')
        if files.exists():
            n = files.count()
            history.append(entry(files.first().occurred_at, f"{n} file{'' if n == 1 else 's'} received", '', '', 'chat'))
        opened = before.filter(kind='file.opened').order_by('occurred_at').first()
        if opened:
            history.append(entry(opened.occurred_at, 'Files opened', '', _name(opened.actor_user), 'work'))
    history.sort(key=lambda h: h['at'])

    return {
        'id': job.pk, 'job_number': job.job_number, 'job_type': job.job_type,
        'owner': {'name': who, 'from_chat': from_chat, 'phone': contact_phone(job), 'jobs_count': others,
                  'conversation_id': conversation.pk if conversation else None},
        'states': {k: {'code': v, 'words': STATE_WORDS.get(v, humanise(v))}
                   for k, v in (('payment', job.payment_state), ('work', job.work_state), ('handover', job.handover_state))},
        'facts': {
            'recorded_by': recorded_by(job), 'recorded_at': job.created_at,
            'channel': humanise(job.intake_channel) or 'Counter',
            'total': f'{job.estimated_cost or 0:.2f}', 'paid': f'{job.amount_paid or 0:.2f}',
            'balance': f'{job.balance_due or 0:.2f}',
            'promised': getattr(job, 'estimated_ready_at', None), 'deadline': job.deadline, 'ready_at': done_at,
        },
        'items': describe_job(job.line_items.select_related('service').order_by('position')),
        'payments': payments,
        'history': history,
        'notes': getattr(job, 'notes', '') or '',
        'can_remind': job.work_state == 'DONE' and job.handover_state == 'AWAITING_COLLECTION',
    }


def remind_now(job, actor):
    """The pickup message, on the BM's request: same words and path as the daily reminder."""
    from apps.jobs.services.labels import contact_phone
    from apps.jobs.services.reminders import _ready_at, _send, first_name, items_phrase, pickup_texts
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record

    if not (job.work_state == 'DONE' and job.handover_state == 'AWAITING_COLLECTION'):
        raise ValueError('Only a finished job waiting for collection can be reminded.')
    phone = contact_phone(job)
    if not phone:
        raise ValueError('There is no number for this customer.')
    ready = timezone.localtime(_ready_at(job))
    wa, sms = pickup_texts(first_name(job), items_phrase(job), 'day7', ready.strftime('%A %d %B'), job.balance_due)
    how = _send(phone, wa, sms, kind='pickup_reminder')
    if not how:
        raise ValueError('The reminder could not be sent just now. Try again later.')
    record(kinds.JOB_PICKUP_REMINDED, actor=Event.STAFF, actor_user=actor, job=job, customer=job.customer,
           branch=job.branch, payload={'step': 'manual', 'by': how}, reason=f'Reminded by the BM, by {how}.')
    return how
