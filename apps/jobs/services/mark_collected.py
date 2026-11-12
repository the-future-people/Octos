"""
Marking a ready job collected, from the BM's Ready for pickup page (12 Nov 2026).

For clearing a backlog: jobs the customer took long ago that nobody marked, and
test jobs. It goes through the status engine's move_handover, the same door the
counter uses, so the shop's rules hold: only a role allowed to move handover
(the BM is an override role), never a job with money owing, and every move
written to the status log and the spine (job.collected) with who and why.
"""

REASONS = {
    'COLLECTED_EARLIER': 'Collected earlier, not marked at the time',
    'TEST_JOB': 'A test job, not a customer\'s work',
    'OTHER': 'Other',
}


class Refused(Exception):
    """Something the BM should be told, in plain words."""


def mark_collected(job, user, reason, note=''):
    from apps.jobs.status_engine import JobStatusEngine

    why = REASONS.get(reason)
    if why is None:
        raise Refused('Choose why this job is being marked collected.')
    if reason == 'OTHER' and not (note or '').strip():
        raise Refused('Say briefly why, for "Other".')
    if job.handover_state == 'HANDED_OVER':
        raise Refused('This job is already marked collected.')

    name = getattr(user, 'full_name', '') or getattr(user, 'email', '') or 'Staff'
    detail = f'{why}: {note.strip()}' if note and note.strip() else why
    try:
        JobStatusEngine(job).move_handover(
            'HANDED_OVER', actor=user,
            notes=f'Marked collected by {name} from Ready for pickup. {detail}',
        )
    except PermissionError:
        raise Refused('Your role cannot mark jobs collected.')
    except ValueError as err:
        raise Refused(str(err) or 'This job cannot be marked collected.')
    return job
