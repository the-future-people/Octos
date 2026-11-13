"""
AttendantSignOffEngine: the attendant's end of day (designed 13 Nov 2026).

The day, from ShiftRoleConfig (no times written here):

  shift end - 30 min   closing soon (a warning, nothing locks)
  shift end            recording closes and sign-off opens, together
  deadline - 15 min    final call
  deadline             Octos signs off for anyone who has not (is_auto)

What the sign-off asks is only what the attendant still owns tonight:

  unpaid instant jobs  she says what happened: coming back, left unpaid,
                       or not printed. Instant work is printed before the
                       customer pays, so an unpaid one may be paper gone
                       with no money. This is the only gate.
  the shelf            every ready production or design job awaiting
                       collection: on the shelf, or missing.

Testimony, not action. The sign-off moves no payment, work or handover
axis: those belong to the cashier, coordinator and attendant respectively,
and closing a loss belongs to the branch manager. The one exception is
NOT_PRODUCED, which is an ordinary cancel through JobStatusEngine, so the
engine's own rules decide whether it is allowed.

The preview is derived fresh every time it is asked for and stores
nothing; only the submitted sign-off is stored, as a snapshot of what was
true when she signed. Every job she recorded on the sheet lands in exactly
one bucket, so the counts always add up to recorded_total.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

ATTENDANT_ROLE = 'ATTENDANT'

# Where each of today's jobs ends up. 'other' catches what fits nowhere
# else (held, routed, an instant job part-paid) so the sum always holds.
BUCKETS = (
    'paid',
    'handed_to_production',
    'awaiting_deposit',
    'unpaid_instant',
    'draft',
    'cancelled',
    'other',
)


class SignOffRefused(Exception):
    """Something the person should be told, in plain words."""


def _iso(dt):
    return dt.isoformat() if dt else None


def _name(user):
    if user is None:
        return ''
    return getattr(user, 'full_name', '') or getattr(user, 'email', '') or 'Staff'


def _role(user):
    return getattr(getattr(user, 'role', None), 'name', '') or ''


def _clock(dt):
    return timezone.localtime(dt).strftime('%I:%M %p').lstrip('0')


class AttendantSignOffEngine:
    WARNING_MINUTES = 30
    FINAL_CALL_MINUTES = 15

    def __init__(self, branch) -> None:
        self.branch = branch

    # ── Timing ────────────────────────────────────────────────────────────────

    def timing(self) -> dict:
        """Today's sign-off times for this branch, all from the shift engine."""
        from apps.hr.shift_engine import ShiftEngine

        schedule = ShiftEngine(self.branch).get_role_schedule(ATTENDANT_ROLE)
        shift_end = datetime.fromisoformat(schedule['shift_end'])
        deadline = datetime.fromisoformat(schedule['signoff_at'])
        return {
            'warning_at': shift_end - timedelta(minutes=self.WARNING_MINUTES),
            'shift_end': shift_end,
            'recording_closes_at': datetime.fromisoformat(schedule['job_lock_at']),
            'final_call_at': deadline - timedelta(minutes=self.FINAL_CALL_MINUTES),
            'deadline': deadline,
        }

    @staticmethod
    def phase(now, timing, signed_off: bool) -> str:
        if signed_off:
            return 'SIGNED_OFF'
        if now < timing['warning_at']:
            return 'OPEN'
        if now < timing['shift_end']:
            return 'CLOSING_SOON'
        if now < timing['final_call_at']:
            return 'SIGN_OFF_OPEN'
        if now < timing['deadline']:
            return 'FINAL_CALL'
        return 'OVERDUE'

    def today_sheet(self):
        from apps.finance.models import DailySalesSheet
        return DailySalesSheet.objects.filter(
            branch=self.branch, date=timezone.localdate(),
        ).first()

    # ── Status (what the attendant portal polls) ──────────────────────────────

    def status(self, attendant, now=None) -> dict:
        from apps.finance.models import AttendantSignOff

        now = now or timezone.now()
        sheet = self.today_sheet()
        timing = self.timing()
        record = (
            AttendantSignOff.objects.filter(daily_sheet=sheet, attendant=attendant).first()
            if sheet else None
        )
        phase = self.phase(now, timing, signed_off=record is not None)
        can_sign_off = bool(
            sheet and sheet.is_open and record is None and now >= timing['shift_end']
        )
        return {
            'sheet_id': sheet.pk if sheet else None,
            'phase': phase,
            'is_signed_off': record is not None,
            'signed_off_at': _iso(record.signed_off_at) if record else None,
            'is_auto': record.is_auto if record else False,
            'can_sign_off': can_sign_off,
            'warning_at': _iso(timing['warning_at']),
            'shift_end': _iso(timing['shift_end']),
            'recording_closes_at': _iso(timing['recording_closes_at']),
            'final_call_at': _iso(timing['final_call_at']),
            'deadline': _iso(timing['deadline']),
            'minutes_to_shift_end': int((timing['shift_end'] - now).total_seconds() // 60),
            'minutes_to_deadline': int((timing['deadline'] - now).total_seconds() // 60),
        }

    # ── Preview (derived, stores nothing) ─────────────────────────────────────

    @staticmethod
    def _credit_covered_ids(jobs_qs) -> set:
        """Jobs whose balance sits on a credit account: paid, as far as the counter goes."""
        return set(
            jobs_qs.filter(
                Q(credit_account__isnull=False)
                | Q(partial_credit_account__isnull=False)
                | Q(customer__credit_account__isnull=False)
            ).values_list('id', flat=True)
        )

    @staticmethod
    def classify(job, credit_covered: bool) -> str:
        """Exactly one bucket for every job. Reads the axes; status only where they can't speak."""
        from apps.jobs.models import Job

        if job.status == Job.DRAFT:
            return 'draft'
        if job.status in (Job.CANCELLED, Job.VOIDED):
            return 'cancelled'
        if job.status == Job.INTAKE_HELD or job.is_routed:
            return 'other'

        if job.job_type == Job.INSTANT:
            if job.payment_state == Job.Payment.SETTLED or credit_covered:
                return 'paid'
            if job.payment_state == Job.Payment.UNPAID:
                return 'unpaid_instant'
            return 'other'

        if job.payment_state in (Job.Payment.DEPOSIT_PAID, Job.Payment.SETTLED) or credit_covered:
            return 'handed_to_production'
        return 'awaiting_deposit'

    @staticmethod
    def _row(job) -> dict:
        customer = ''
        if job.customer_id:
            try:
                customer = getattr(job.customer, 'name', '') or str(job.customer)
            except Exception:
                customer = ''
        return {
            'id': job.pk,
            'job_number': job.job_number,
            'title': job.title,
            'job_type': job.job_type,
            'amount': str(job.estimated_cost or Decimal('0.00')),
            'customer': customer,
            'recorded_at': _iso(job.created_at),
        }

    def shelf_jobs(self):
        """Ready production and design work waiting to be collected: what should be on the shelf."""
        from apps.jobs.models import Job
        return (
            Job.objects.filter(
                branch=self.branch,
                job_type__in=[Job.PRODUCTION, Job.DESIGN],
                work_state=Job.Work.DONE,
                handover_state=Job.Handover.AWAITING_COLLECTION,
            )
            .exclude(status__in=[Job.CANCELLED, Job.VOIDED])
            .select_related('customer')
            .order_by('updated_at')
        )

    def preview(self, attendant, sheet) -> dict:
        from apps.jobs.models import Job

        jobs_qs = Job.objects.filter(daily_sheet=sheet, intake_by=attendant)
        covered = self._credit_covered_ids(jobs_qs)
        jobs = list(jobs_qs.select_related('customer').order_by('created_at'))

        buckets = {b: 0 for b in BUCKETS}
        lists = {b: [] for b in BUCKETS}
        for job in jobs:
            bucket = self.classify(job, job.pk in covered)
            buckets[bucket] += 1
            row = self._row(job)
            if bucket == 'handed_to_production':
                row['ready_at'] = _iso(job.estimated_ready_at)
            if bucket == 'draft':
                row['expires_at'] = _iso(job.draft_expires_at)
            lists[bucket].append(row)
        buckets['recorded_total'] = len(jobs)

        return {
            'sheet_id': sheet.pk,
            'sheet_number': sheet.sheet_number,
            'buckets': buckets,
            'unpaid_instant': lists['unpaid_instant'],
            'handed_to_production': lists['handed_to_production'],
            'awaiting_deposit': lists['awaiting_deposit'],
            'drafts': lists['draft'],
            'other': lists['other'],
            'shelf': [self._row(j) for j in self.shelf_jobs()],
        }

    # ── Submit ────────────────────────────────────────────────────────────────

    def submit(self, attendant, unpaid_answers: dict, shelf_answers: dict,
               handover_note: str = '', now=None):
        """
        Record the attendant's sign-off. Every unpaid instant job and every
        shelf job must be answered; the lists are worked out again here, so
        what she answered is checked against the facts as they are now.
        """
        from apps.finance.models import AttendantSignOff, AttendantSignOffItem
        from apps.jobs.models import Job
        from apps.jobs.status_engine import JobStatusEngine

        Item = AttendantSignOffItem
        now = now or timezone.now()

        if _role(attendant) != ATTENDANT_ROLE:
            raise SignOffRefused('Only an attendant can sign off here.')

        sheet = self.today_sheet()
        if sheet is None or not sheet.is_open:
            raise SignOffRefused('There is no open day sheet to sign off against.')

        timing = self.timing()
        if now < timing['shift_end']:
            raise SignOffRefused(f"Sign-off opens at {_clock(timing['shift_end'])}.")

        if AttendantSignOff.objects.filter(daily_sheet=sheet, attendant=attendant).exists():
            raise SignOffRefused('You have already signed off today.')

        preview = self.preview(attendant, sheet)
        unpaid_answers = {str(k): v for k, v in (unpaid_answers or {}).items()}
        shelf_answers = {str(k): v for k, v in (shelf_answers or {}).items()}

        unpaid_choices = {a.value for a in (
            Item.Answer.COMING_BACK, Item.Answer.LEFT_UNPAID, Item.Answer.NOT_PRODUCED)}
        shelf_choices = {a.value for a in (Item.Answer.ON_SHELF, Item.Answer.MISSING)}

        unanswered = [
            r['job_number'] for r in preview['unpaid_instant']
            if unpaid_answers.get(str(r['id'])) not in unpaid_choices
        ] + [
            r['job_number'] for r in preview['shelf']
            if shelf_answers.get(str(r['id'])) not in shelf_choices
        ]
        if unanswered:
            shown = ', '.join(unanswered[:5])
            more = f' and {len(unanswered) - 5} more' if len(unanswered) > 5 else ''
            raise SignOffRefused(f'Answer every job before signing off: {shown}{more}.')

        left_unpaid_value = sum(
            (Decimal(r['amount']) for r in preview['unpaid_instant']
             if unpaid_answers[str(r['id'])] == Item.Answer.LEFT_UNPAID),
            Decimal('0.00'),
        )
        not_produced = [
            r for r in preview['unpaid_instant']
            if unpaid_answers[str(r['id'])] == Item.Answer.NOT_PRODUCED
        ]
        missing_count = sum(
            1 for r in preview['shelf'] if shelf_answers[str(r['id'])] == Item.Answer.MISSING
        )

        # The snapshot shows the day as it stands after her answers: a job
        # she says was never printed is cancelled, not unpaid.
        buckets = dict(preview['buckets'])
        buckets['unpaid_instant'] -= len(not_produced)
        buckets['cancelled'] += len(not_produced)

        with transaction.atomic():
            try:
                with transaction.atomic():
                    record = AttendantSignOff.objects.create(
                        attendant=attendant,
                        daily_sheet=sheet,
                        signed_off_at=now,
                        signed_off_by=attendant,
                        is_auto=False,
                        handover_note=(handover_note or '').strip()[:2000],
                        buckets=buckets,
                        left_unpaid_value=left_unpaid_value,
                        missing_count=missing_count,
                    )
            except IntegrityError:
                raise SignOffRefused('You have already signed off today.')

            for r in preview['unpaid_instant']:
                Item.objects.create(
                    signoff=record, job_id=r['id'], kind=Item.Kind.UNPAID_INSTANT,
                    answer=unpaid_answers[str(r['id'])], amount=Decimal(r['amount']),
                )
            for r in preview['shelf']:
                Item.objects.create(
                    signoff=record, job_id=r['id'], kind=Item.Kind.SHELF,
                    answer=shelf_answers[str(r['id'])], amount=Decimal(r['amount']),
                )

            for r in not_produced:
                job = Job.objects.select_for_update().get(pk=r['id'])
                try:
                    JobStatusEngine(job).transition(
                        'CANCELLED', actor=attendant,
                        notes="Not printed. Cancelled at the attendant's sign-off.",
                    )
                except (ValueError, PermissionError) as err:
                    raise SignOffRefused(f"{job.job_number} could not be cancelled: {err}")

            transaction.on_commit(lambda: self._tell_managers_about(record))

        logger.info(
            'AttendantSignOff: %s signed off sheet %s (%s left unpaid, %s missing)',
            attendant.pk, sheet.pk, left_unpaid_value, missing_count,
        )
        return record

    # ── Automatic sign-off at the deadline ────────────────────────────────────

    def attendants_due(self, sheet):
        """Attendants who recorded anything on this sheet: they are the ones who must sign off."""
        from apps.accounts.models import CustomUser
        from apps.jobs.models import Job

        ids = (
            Job.objects.filter(daily_sheet=sheet, intake_by__role__name=ATTENDANT_ROLE)
            .values_list('intake_by_id', flat=True)
            .distinct()
        )
        return CustomUser.objects.filter(pk__in=list(ids)).order_by('first_name', 'last_name')

    def auto_signoff(self, sheet, now=None) -> list:
        """
        Past the deadline, sign off everyone due who has not, as Octos.
        Idempotent: the unique constraint is the guarantee, so a manual
        sign-off landing at the same moment simply wins.
        """
        from apps.accounts.system import require_octos_user
        from apps.finance.models import AttendantSignOff

        now = now or timezone.now()
        if not sheet.is_open:
            return []
        timing = self.timing()
        if now < timing['deadline']:
            return []

        done = set(
            AttendantSignOff.objects.filter(daily_sheet=sheet).values_list('attendant_id', flat=True)
        )
        due = [a for a in self.attendants_due(sheet) if a.pk not in done]
        if not due:
            return []

        octos = require_octos_user()
        created = []
        for attendant in due:
            preview = self.preview(attendant, sheet)
            try:
                with transaction.atomic():
                    record = AttendantSignOff.objects.create(
                        attendant=attendant,
                        daily_sheet=sheet,
                        signed_off_at=timing['deadline'],
                        signed_off_by=octos,
                        is_auto=True,
                        buckets=preview['buckets'],
                    )
            except IntegrityError:
                continue
            created.append(record)
            self._tell_managers_about(record, unexplained=preview['buckets']['unpaid_instant'])

        return created

    # ── The branch manager's side ─────────────────────────────────────────────

    def gate(self, sheet, now=None) -> dict:
        """
        Close gate: everyone who recorded jobs today has signed off. Past the
        deadline the automatic sign-off is run first, so the manager is
        never held up waiting for the five-minute task.
        """
        from apps.finance.models import AttendantSignOff

        now = now or timezone.now()
        errors = []
        try:
            self.auto_signoff(sheet, now=now)
        except RuntimeError as err:
            errors.append(str(err))

        signed = set(
            AttendantSignOff.objects.filter(daily_sheet=sheet).values_list('attendant_id', flat=True)
        )
        deadline = _clock(self.timing()['deadline'])
        for attendant in self.attendants_due(sheet):
            if attendant.pk not in signed:
                errors.append(
                    f'{_name(attendant)} has not signed off yet (deadline {deadline}).'
                )
        return {'passed': not errors, 'errors': errors}

    def sheet_overview(self, sheet) -> dict:
        """Every attendant's sign-off for a sheet, with what still needs the manager."""
        from apps.finance.models import AttendantSignOff

        records = {
            r.attendant_id: r
            for r in AttendantSignOff.objects.filter(daily_sheet=sheet)
            .select_related('attendant', 'signed_off_by')
            .prefetch_related('items__job')
        }
        people = {a.pk: a for a in self.attendants_due(sheet)}
        for attendant_id, record in records.items():
            people.setdefault(attendant_id, record.attendant)

        rows = []
        for attendant_id, attendant in people.items():
            record = records.get(attendant_id)
            open_items = []
            if record:
                for item in record.items.all():
                    if item.needs_bm:
                        open_items.append({
                            'id': item.pk,
                            'kind': item.kind,
                            'answer': item.answer,
                            'answer_label': item.get_answer_display(),
                            'job_id': item.job_id,
                            'job_number': item.job.job_number,
                            'title': item.job.title,
                            'amount': str(item.amount),
                        })
            rows.append({
                'attendant_id': attendant_id,
                'attendant_name': _name(attendant),
                'is_signed_off': record is not None,
                'signed_off_at': _iso(record.signed_off_at) if record else None,
                'is_auto': record.is_auto if record else False,
                'buckets': record.buckets if record else {},
                'handover_note': record.handover_note if record else '',
                'left_unpaid_value': str(record.left_unpaid_value) if record else '0.00',
                'missing_count': record.missing_count if record else 0,
                'open_items': open_items,
            })

        rows.sort(key=lambda r: r['attendant_name'])
        return {
            'all_signed_off': all(r['is_signed_off'] for r in rows),
            'deadline': _iso(self.timing()['deadline']),
            'attendants': rows,
        }

    @staticmethod
    def resolve_item(item_id, user, note: str, now=None):
        """
        The manager deals with a flagged answer. A job left unpaid is
        cancelled with the reason on its log, unless it has been paid since.
        Nothing is voided: the void rules were never finalised.
        """
        from apps.finance.models import AttendantSignOffItem
        from apps.jobs.models import Job
        from apps.jobs.status_engine import AXIS_OVERRIDE_ROLES, JobStatusEngine

        now = now or timezone.now()
        note = (note or '').strip()

        if _role(user) not in AXIS_OVERRIDE_ROLES:
            raise SignOffRefused('Only a branch manager can resolve this.')
        if not note:
            raise SignOffRefused('Say briefly what happened before resolving.')

        with transaction.atomic():
            try:
                item = AttendantSignOffItem.objects.select_for_update().get(pk=item_id)
            except AttendantSignOffItem.DoesNotExist:
                raise SignOffRefused('That item no longer exists.')

            branch_id = item.signoff.daily_sheet.branch_id
            if getattr(user, 'branch_id', None) not in (None, branch_id):
                raise SignOffRefused('This item belongs to another branch.')
            if not item.needs_bm:
                raise SignOffRefused('This has already been resolved.')

            resolution = note
            if item.answer == AttendantSignOffItem.Answer.LEFT_UNPAID:
                job = Job.objects.select_for_update().get(pk=item.job_id)
                still_unpaid = (
                    job.payment_state == Job.Payment.UNPAID
                    and job.status not in (Job.CANCELLED, Job.VOIDED)
                )
                if still_unpaid:
                    try:
                        JobStatusEngine(job).transition(
                            'CANCELLED', actor=user,
                            notes=f'Customer left without paying. Written off by {_name(user)}: {note}',
                        )
                    except (ValueError, PermissionError) as err:
                        raise SignOffRefused(f'{job.job_number} could not be cancelled: {err}')
                    resolution = f'Written off: {note}'
                else:
                    resolution = f'No write-off needed, the job has moved on since: {note}'

            item.resolved_by = user
            item.resolved_at = now
            item.resolution_note = resolution
            item.save(update_fields=['resolved_by', 'resolved_at', 'resolution_note', 'updated_at'])
        return item

    # ── Telling the managers ──────────────────────────────────────────────────

    def _managers(self):
        from apps.accounts.models import CustomUser
        return CustomUser.objects.filter(
            branch=self.branch, role__name='BRANCH_MANAGER', is_active=True,
        )

    def _tell_managers_about(self, record, unexplained: int = 0) -> None:
        """One message per sign-off, and only when there is something to act on."""
        from apps.notifications.models import Notification
        from apps.notifications.services import notify_many

        who = _name(record.attendant)
        parts = []
        if record.is_auto:
            parts.append(
                f'{who} did not sign off by {_clock(record.signed_off_at)}, '
                f'so Octos signed off for them.'
            )
            if unexplained:
                parts.append(
                    f'{unexplained} unpaid instant job{"s" if unexplained != 1 else ""} '
                    f'were not explained.'
                )
        else:
            flagged = list(record.items.filter(answer__in=['LEFT_UNPAID', 'MISSING']))
            left = [i for i in flagged if i.answer == 'LEFT_UNPAID']
            missing = [i for i in flagged if i.answer == 'MISSING']
            if left:
                parts.append(
                    f'{who} says {len(left)} customer{"s" if len(left) != 1 else ""} '
                    f'left without paying (GHS {record.left_unpaid_value}).'
                )
            if missing:
                parts.append(
                    f'{who} could not find {len(missing)} ready '
                    f'job{"s" if len(missing) != 1 else ""} on the shelf.'
                )
        if not parts:
            return
        parts.append('Review it in the day sheet before closing.')
        try:
            notify_many(
                recipients=self._managers(),
                verb=Notification.Verb.SYSTEM,
                message=' '.join(parts),
            )
        except Exception:
            logger.exception('AttendantSignOff: could not notify managers for %s', record.pk)
