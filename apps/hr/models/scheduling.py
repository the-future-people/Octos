from django.db import models
from apps.core.models import AuditModel


class EmployeeShift(AuditModel):
    """
    Base recurring shift schedule for an employee.
    Defines what days and hours an employee normally works.
    """

    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6

    DAY_CHOICES = [
        (MON, 'Monday'),
        (TUE, 'Tuesday'),
        (WED, 'Wednesday'),
        (THU, 'Thursday'),
        (FRI, 'Friday'),
        (SAT, 'Saturday'),
        (SUN, 'Sunday'),
    ]

    employee   = models.ForeignKey(
        'hr.Employee',
        on_delete=models.CASCADE,
        related_name='shifts',
    )
    branch     = models.ForeignKey(
        'organization.Branch',
        on_delete=models.CASCADE,
        related_name='shifts',
    )
    day_of_week  = models.IntegerField(choices=DAY_CHOICES)
    start_time   = models.TimeField()
    end_time     = models.TimeField()
    is_active    = models.BooleanField(default=True)

    class Meta:
        ordering = ['employee', 'day_of_week', 'start_time']
        unique_together = ['employee', 'day_of_week']

    def __str__(self):
        return (
            f"{self.employee.full_name} — "
            f"{self.get_day_of_week_display()} "
            f"{self.start_time.strftime('%H:%M')}–{self.end_time.strftime('%H:%M')}"
        )


class ShiftOverride(AuditModel):
    """
    A one-off override for a specific date that supersedes the base EmployeeShift.
    Created automatically when a ShiftSwap is approved, or manually by BM.
    """

    SWAP     = 'SWAP'
    OVERTIME = 'OVERTIME'
    COVER    = 'COVER'
    ABSENCE  = 'ABSENCE'

    OVERRIDE_TYPE_CHOICES = [
        (SWAP,     'Swap'),
        (OVERTIME, 'Overtime'),
        (COVER,    'Cover'),
        (ABSENCE,  'Absence'),
    ]

    employee        = models.ForeignKey(
        'hr.Employee',
        on_delete=models.CASCADE,
        related_name='shift_overrides',
    )
    date            = models.DateField()
    original_shift  = models.ForeignKey(
        EmployeeShift,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='overrides',
    )
    override_type   = models.CharField(max_length=20, choices=OVERRIDE_TYPE_CHOICES)
    override_start  = models.TimeField(null=True, blank=True)
    override_end    = models.TimeField(null=True, blank=True)
    swap_ref        = models.ForeignKey(
        'hr.EmployeeShiftSwap',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='overrides',
    )
    notes           = models.TextField(blank=True)

    class Meta:
        ordering = ['date', 'employee']
        unique_together = ['employee', 'date', 'override_type']

    def __str__(self):
        return (
            f"{self.employee.full_name} — "
            f"{self.date} [{self.override_type}]"
        )


class EmployeeShiftSwap(AuditModel):
    """
    A formal shift swap request between two employees.
    Both employees must agree, then BM must approve.
    Compensation (payback shift) is mandatory — no one-way swaps.
    """

    PENDING   = 'PENDING'
    ACCEPTED  = 'ACCEPTED'   # B accepted, awaiting BM
    REJECTED  = 'REJECTED'   # B rejected
    APPROVED  = 'APPROVED'   # BM approved → overrides created
    DECLINED  = 'DECLINED'   # BM declined
    CANCELLED = 'CANCELLED'  # initiator cancelled before approval

    STATUS_CHOICES = [
        (PENDING,   'Pending Acceptance'),
        (ACCEPTED,  'Accepted — Awaiting BM Approval'),
        (REJECTED,  'Rejected by Peer'),
        (APPROVED,  'Approved'),
        (DECLINED,  'Declined by Manager'),
        (CANCELLED, 'Cancelled'),
    ]

    # ── Parties ───────────────────────────────────────────
    initiated_by  = models.ForeignKey(
        'hr.Employee',
        on_delete=models.PROTECT,
        related_name='swaps_initiated',
    )
    accepted_by   = models.ForeignKey(
        'hr.Employee',
        on_delete=models.PROTECT,
        related_name='swaps_accepted',
    )
    approved_by   = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='swaps_approved',
    )

    # ── Status ────────────────────────────────────────────
    status        = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    reason        = models.TextField()  # why A needs the swap (mandatory)
    bm_notes      = models.TextField(blank=True)  # BM rejection/approval notes

    # ── The swap: A gives away their shift on initiator_date ─
    initiator_date  = models.DateField()   # date A needs off
    initiator_shift = models.ForeignKey(
        EmployeeShift,
        on_delete=models.PROTECT,
        related_name='swaps_as_initiator',
    )  # A's shift being given away

    # ── Cover: B covers A's shift on cover_date ───────────
    cover_date    = models.DateField()     # date B covers A (same as initiator_date usually)
    cover_shift   = models.ForeignKey(
        EmployeeShift,
        on_delete=models.PROTECT,
        related_name='swaps_as_cover',
    )  # the shift B will work on cover_date

    # ── Compensation: A covers B's shift on compensation_date
    compensation_date  = models.DateField()   # date A pays back
    compensation_shift = models.ForeignKey(
        EmployeeShift,
        on_delete=models.PROTECT,
        related_name='swaps_as_compensation',
    )  # B's shift that A will cover as payback

    # ── Timestamps ────────────────────────────────────────
    accepted_at   = models.DateTimeField(null=True, blank=True)
    approved_at   = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return (
            f"Swap: {self.initiated_by.full_name} ↔ {self.accepted_by.full_name} "
            f"[{self.initiator_date}] — {self.status}"
        )

    def approve(self, approved_by):
        """
        BM approves the swap. Creates all 4 ShiftOverride records.
        Call this inside a transaction.
        """
        from django.utils import timezone

        self.status      = self.APPROVED
        self.approved_by = approved_by
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

        # 1. A is absent on initiator_date (their original shift)
        ShiftOverride.objects.get_or_create(
            employee       = self.initiated_by,
            date           = self.initiator_date,
            override_type  = ShiftOverride.ABSENCE,
            defaults=dict(
                original_shift = self.initiator_shift,
                swap_ref       = self,
                notes          = f"Swapped with {self.accepted_by.full_name}",
            ),
        )

        # 2. B covers A's shift on cover_date
        ShiftOverride.objects.get_or_create(
            employee       = self.accepted_by,
            date           = self.cover_date,
            override_type  = ShiftOverride.SWAP,
            defaults=dict(
                original_shift = self.cover_shift,
                override_start = self.initiator_shift.start_time,
                override_end   = self.initiator_shift.end_time,
                swap_ref       = self,
                notes          = f"Covering {self.initiated_by.full_name}",
            ),
        )

        # 3. A covers B's shift on compensation_date (payback)
        ShiftOverride.objects.get_or_create(
            employee       = self.initiated_by,
            date           = self.compensation_date,
            override_type  = ShiftOverride.SWAP,
            defaults=dict(
                original_shift = self.compensation_shift,
                override_start = self.compensation_shift.start_time,
                override_end   = self.compensation_shift.end_time,
                swap_ref       = self,
                notes          = f"Compensation for {self.accepted_by.full_name}",
            ),
        )

        # 4. B is absent during their normal slot on compensation_date
        ShiftOverride.objects.get_or_create(
            employee       = self.accepted_by,
            date           = self.compensation_date,
            override_type  = ShiftOverride.ABSENCE,
            defaults=dict(
                original_shift = self.compensation_shift,
                swap_ref       = self,
                notes          = f"A ({self.initiated_by.full_name}) compensating",
            ),
        )