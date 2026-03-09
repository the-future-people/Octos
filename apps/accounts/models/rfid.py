from django.db import models
from apps.core.models import AuditModel


class RFIDAccessLog(AuditModel):
    """
    Logs every physical RFID/NFC card scan at any branch entrance.
    Every entry and exit is recorded against the employee and branch.
    """
    ACTION_CHOICES = [
        ('CLOCK_IN', 'Clock In'),
        ('CLOCK_OUT', 'Clock Out'),
        ('DENIED', 'Access Denied'),
    ]

    employee = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='rfid_logs'
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='rfid_logs'
    )
    card_uid = models.CharField(max_length=100)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.employee.full_name} — {self.action} at {self.branch.name}"