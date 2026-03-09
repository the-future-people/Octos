from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
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
    Every user must belong to a branch and have a role.
    No personal contact details are ever used for business.
    """
    employee_id = models.CharField(max_length=20, unique=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    photo = models.ImageField(upload_to='employees/', null=True, blank=True)

    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='user_accounts',
        null=True,
        blank=True
    )
    role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='users',
        null=True,
        blank=True
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_clocked_in = models.BooleanField(default=False)
    last_clock_in = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
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

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_superuser