from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.contrib.auth.hashers import make_password, check_password
from apps.core.models import AuditModel


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, AuditModel):
    """
    The central user model for all Octos staff.
    Operational staff (BM, cashier, attendant) have branch set.
    Regional Managers have region set, branch null.
    Belt Managers and above have both null.

    employment_status tracks the operational state of the employee,
    separate from is_active (which controls login access entirely).

      SHADOW   — pre-start-date, read-only portal access granted
      ACTIVE   — full access, normal operations
      INACTIVE — departed or suspended; is_active should also be False
    """

    # ── Employment status ────────────────────────────────────
    SHADOW   = 'SHADOW'
    ACTIVE   = 'ACTIVE'
    INACTIVE = 'INACTIVE'

    EMPLOYMENT_STATUS_CHOICES = [
        (SHADOW,   'Shadow'),
        (ACTIVE,   'Active'),
        (INACTIVE, 'Inactive'),
    ]

    employee_id = models.CharField(max_length=20, unique=True, blank=True)
    first_name  = models.CharField(max_length=100)
    last_name   = models.CharField(max_length=100)
    email       = models.EmailField(unique=True)
    phone       = models.CharField(max_length=20, blank=True)
    photo       = models.ImageField(upload_to='employees/', null=True, blank=True)

    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='user_accounts',
        null=True, blank=True,
    )
    region = models.ForeignKey(
        'organization.Region',
        on_delete=models.PROTECT,
        related_name='user_accounts',
        null=True, blank=True,
    )
    role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='users',
        null=True, blank=True,
    )

    employment_status = models.CharField(
        max_length=10,
        choices=EMPLOYMENT_STATUS_CHOICES,
        default=ACTIVE,
        help_text=(
            'Operational state of the employee. '
            'SHADOW = read-only pre-start access. '
            'ACTIVE = full access. '
            'INACTIVE = departed or suspended.'
        ),
    )

    is_active      = models.BooleanField(default=True)
    is_staff       = models.BooleanField(default=False)
    is_superuser   = models.BooleanField(default=False)
    is_clocked_in  = models.BooleanField(default=False)
    last_clock_in  = models.DateTimeField(null=True, blank=True)
    approved_at    = models.DateTimeField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)

    # ── Download PIN ─────────────────────────────────────────
    # Stored as a hashed 4-digit PIN — never plain text
    download_pin     = models.CharField(max_length=128, blank=True, null=True)
    download_pin_set = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        ordering = ['first_name', 'last_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.employee_id})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def is_approved(self):
        return self.approved_at is not None

    @property
    def is_shadow(self):
        return self.employment_status == self.SHADOW

    def set_download_pin(self, raw_pin):
        """Hash and store the 4-digit PIN."""
        self.download_pin     = make_password(str(raw_pin))
        self.download_pin_set = True
        self.save(update_fields=['download_pin', 'download_pin_set'])

    def verify_download_pin(self, raw_pin):
        """Check a raw PIN against the stored hash."""
        if not self.download_pin:
            return False
        return check_password(str(raw_pin), self.download_pin)

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_superuser