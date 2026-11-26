"""
A job's name for people (26 Nov 2026, Khofi: "FP-WLB-2026-05286" is for
the system, not for reading).

    short_ref('FP-WLB-2026-05286')  ->  '#5286'
    job_name(job)                    ->  "Kwabena's Flexy Banner (#5286)"

Who and what, with the short number to find it by. The full number stays
on receipts, proformas, invoices, QR codes and in the database, and every
search takes "5286", "05286" or the whole thing.

The short number restarts each January and each branch counts its own, so
it is only ever shown with its who and what beside it.
"""


def short_ref(job_number):
    """'#5286' for FP-WLB-2026-05286; the number as it is when it has no tail."""
    tail = (job_number or '').rsplit('-', 1)[-1].lstrip('0')
    return f'#{tail}' if tail.isdigit() else (job_number or '')


def what_of(job):
    """The job's first line, as the title starts: 'Flexy Banner', not every detail."""
    title = (getattr(job, 'title', '') or '').strip()
    what = title.split(' · ', 1)[0].strip()
    more = ''
    if ' and ' in title and title.rstrip().endswith('more'):
        more = ' and ' + title.rsplit(' and ', 1)[1].strip()
    return (what + more) if what else 'job'


def _whose(job):
    customer = getattr(job, 'customer', None) if getattr(job, 'customer_id', None) else None
    if customer is None:
        return ''
    if getattr(customer, 'customer_type', '') not in ('', 'INDIVIDUAL') and getattr(customer, 'company_name', ''):
        name = customer.company_name.strip()
    else:
        name = (getattr(customer, 'first_name', '') or '').strip() or (getattr(customer, 'full_name', '') or '').strip()
    return name


def job_name(job):
    """"Kwabena's Flexy Banner (#5286)", or "Walk-in Flexy Banner (#5286)" with no customer."""
    whose = _whose(job)
    lead = f"{whose}'s" if whose else 'Walk-in'
    return f'{lead} {what_of(job)} ({short_ref(job.job_number)})'
