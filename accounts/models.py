from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils.crypto import salted_hmac


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).strip().lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", self.model.Role.ADMIN)
        if extra_fields["is_staff"] is not True or extra_fields["is_superuser"] is not True:
            raise ValueError("A superuser must have staff and superuser permissions.")
        if extra_fields["role"] != self.model.Role.ADMIN:
            raise ValueError("A superuser must have the Administrator role.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        TEACHER = "teacher", "Teacher"
        ADMIN = "admin", "Administrator"

    class Designation(models.TextChoices):
        SCHOOL_DIRECTOR = "school_director", "School Director"
        PRINCIPAL = "principal", "Principal"
        ASSISTANT_PRINCIPAL = "assistant_principal", "Assistant Principal"

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Not approved"

    def _get_session_auth_hash(self, secret=None):
        """Expire sessions created before portal-wide MFA became mandatory."""
        session_hash = super()._get_session_auth_hash(secret=secret)
        return salted_hmac(
            "accounts.User.portal_mfa_session.v1",
            session_hash,
            secret=secret,
        ).hexdigest()

    username = None
    email = models.EmailField(unique=True)
    keycloak_subject = models.CharField(max_length=255, blank=True, null=True, unique=True)
    full_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=32, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STUDENT)
    designation = models.CharField(max_length=32, choices=Designation.choices, blank=True, default="")
    approval_status = models.CharField(
        max_length=16,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.APPROVED,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        "self",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_accounts",
    )
    locked_until = models.DateTimeField(blank=True, null=True)
    must_change_password = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = UserManager()

    class Meta:
        constraints = [models.UniqueConstraint(Lower("email"), name="unique_user_email_ci")]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_portal_admin(self):
        return self.is_active and self.role == self.Role.ADMIN and self.is_staff and self.is_superuser

    @property
    def is_portal_teacher(self):
        return (
            self.is_active
            and self.role == self.Role.TEACHER
            and self.approval_status == self.ApprovalStatus.APPROVED
        )

    @property
    def can_manage_all_students(self):
        return (
            self.is_portal_teacher
            and self.email.lower() == settings.AUTHSHIELD_SCHOOLWIDE_TEACHER_EMAIL
        )

    @property
    def is_portal_student(self):
        return (
            self.is_active
            and self.role == self.Role.STUDENT
            and self.approval_status == self.ApprovalStatus.APPROVED
        )

    def __str__(self):
        return self.full_name or self.email


class EmailOTPChallenge(models.Model):
    class Purpose(models.TextChoices):
        SIGN_IN = "sign_in", "Sign in"
        EMAIL_STEP_UP = "email_step_up", "Additional sign-in verification"
        PASSWORD_RESET = "password_reset", "Password reset"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_otp_challenges")
    purpose = models.CharField(max_length=24, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128, blank=True, default="")
    sent_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "purpose"), name="unique_user_email_otp_purpose"),
        ]


class PasswordResetRequestLimit(models.Model):
    """A persistent per-source counter for password recovery requests."""

    fingerprint = models.CharField(max_length=64, unique=True)
    window_started_at = models.DateTimeField()
    request_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=("window_started_at",), name="pwd_reset_limit_window_idx")]


class PublicRequestThrottle(models.Model):
    """A short-lived, cross-instance quota for unauthenticated portal requests."""

    purpose = models.CharField(max_length=32)
    fingerprint = models.CharField(max_length=64)
    window_started_at = models.DateTimeField()
    request_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("purpose", "fingerprint"), name="unique_public_throttle_bucket"),
        ]
        indexes = [models.Index(fields=("window_started_at",), name="public_throttle_window_idx")]


class SMSOTPDeliveryLimit(models.Model):
    """Persistent per-account SMS throttle shared across sign-in sessions."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sms_otp_delivery_limit",
    )
    window_started_at = models.DateTimeField()
    last_requested_at = models.DateTimeField(blank=True, null=True)
    request_count = models.PositiveSmallIntegerField(default=0)
    verification_attempts = models.PositiveSmallIntegerField(default=0)


class RoleMFAPolicy(models.Model):
    """Portal OTP policy for one account role."""

    role = models.CharField(max_length=16, choices=User.Role.choices, unique=True)
    enabled = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)
    email_enabled = models.BooleanField(default=False)
    require_both_factors = models.BooleanField(default=False)
    include_otp_exempt_accounts = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="updated_mfa_policies",
    )

    class Meta:
        ordering = ("role",)

    def __str__(self):
        return f"{self.get_role_display()} MFA policy"


class KeycloakMFAPolicy(models.Model):
    """State of the portal's Keycloak authenticator-app OTP flow switch."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    totp_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="updated_keycloak_mfa_policies",
    )

    def __str__(self):
        return "Keycloak authenticator-app MFA policy"
