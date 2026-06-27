from django.db import models
from django.contrib.auth.hashers import make_password, check_password


class NotePin(models.Model):
    """
    A 4-digit PIN gating access to a user's Personal Notes.
    Stored hashed — never plaintext. One PIN per user.

    Verification happens once per "session" of viewing Notes — the
    frontend re-prompts every time the Notes section is entered,
    including after idle-redirect away from it.
    """

    owner    = models.OneToOneField(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='note_pin',
    )
    pin_hash   = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Note PIN'
        verbose_name_plural = 'Note PINs'

    def set_pin(self, raw_pin: str):
        self.pin_hash = make_password(raw_pin)

    def check_pin(self, raw_pin: str) -> bool:
        return check_password(raw_pin, self.pin_hash)

    def __str__(self):
        return f'PIN for owner {self.owner_id}'