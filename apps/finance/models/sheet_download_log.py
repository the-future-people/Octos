from django.db import models
from apps.core.models import AuditModel


class SheetDownloadLog(models.Model):
    """
    Audit trail for every daily sheet PDF download.
    Records who downloaded, when, which sheet, and from which IP.
    HQ can query this to monitor download activity across branches.
    """
    sheet         = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete=models.PROTECT,
        related_name='download_logs',
    )
    downloaded_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='sheet_downloads',
    )
    downloaded_at = models.DateTimeField(auto_now_add=True)
    ip_address    = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-downloaded_at']

    def __str__(self):
        return f"{self.downloaded_by} downloaded sheet {self.sheet.date} at {self.downloaded_at}"