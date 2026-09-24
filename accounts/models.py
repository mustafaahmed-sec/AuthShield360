from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


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

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Not approved"

    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=32, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STUDENT)
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
    def is_portal_student(self):
        return (
            self.is_active
            and self.role == self.Role.STUDENT
            and self.approval_status == self.ApprovalStatus.APPROVED
        )

    def __str__(self):
        return self.full_name or self.email
