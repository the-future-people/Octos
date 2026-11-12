"""
Who a job is for, who recorded it, and how to reach them: one answer for
every screen (12 Nov 2026).

The BM's workload pages, the cashier's queue and receipts all ask these, so
they are answered once, here:

  for_whom      the customer record, else the WhatsApp chat the job is linked
                to ("Linc (WhatsApp @linc_gh)"), else "Walk-in"
  recorded_by   the attendant, else how it came in ("Print Octos (online)"),
                else a dash
  contact_phone the customer's phone, else the chat's number, else ''
"""

CHANNEL_LABEL = {
    'ONLINE': 'Print Octos (online)',
    'WHATSAPP': 'WhatsApp order',
    'EMAIL': 'Email order',
    'PHONE': 'Phone order',
}


def _chat(job):
    from apps.communications.services.chat_customer import chat_identity
    return chat_identity(job)


def for_whom(job):
    """(label, from_chat) for this job."""
    if getattr(job, 'customer_id', None):
        return job.customer.display_name or 'Customer', False
    who = _chat(job)
    return (who[0], True) if who else ('Walk-in', False)


def recorded_by(job):
    """The attendant who recorded it, else how it came in, else a dash."""
    name = getattr(job.intake_by, 'full_name', '') if getattr(job, 'intake_by_id', None) else ''
    return name or CHANNEL_LABEL.get(getattr(job, 'intake_channel', ''), '—')


def contact_phone(job):
    """A number to send the receipt to: the customer's, else the chat's."""
    if getattr(job, 'customer_id', None) and getattr(job.customer, 'phone', ''):
        return job.customer.phone
    who = _chat(job)
    return who[1] if who else ''
