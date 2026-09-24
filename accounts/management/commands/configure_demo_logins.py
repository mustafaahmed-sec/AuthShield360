"""Prepare local fictional logins from secrets held in the ignored .env file."""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Set passwords for the fictional demo accounts from local environment variables."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.AUTHSHIELD_BASELINE_LOGIN_ENABLED:
            raise CommandError("Demo passwords can be prepared only for the local baseline stage.")

        names = (
            "DEMO_STUDENT_PASSWORD",
            "DEMO_TEACHER_PASSWORD",
            "DEMO_ADMIN_PASSWORD",
        )
        passwords = {name: os.environ.get(name, "") for name in names}
        if any(len(value) < 16 for value in passwords.values()):
            raise CommandError("Set all three DEMO_*_PASSWORD values to at least 16 characters in the ignored .env file.")

        User = get_user_model()
        accounts = (
            ("ali.student@example.test", "Ali Khan", User.Role.STUDENT, "DEMO_STUDENT_PASSWORD"),
            ("mina.teacher@example.test", "Mina Rahman", User.Role.TEACHER, "DEMO_TEACHER_PASSWORD"),
            ("sara.admin@example.test", "Sara Ahmed", User.Role.ADMIN, "DEMO_ADMIN_PASSWORD"),
        )
        for email, full_name, role, password_name in accounts:
            user, _ = User.objects.get_or_create(email=email)
            user.full_name = full_name
            user.role = role
            user.is_active = True
            user.is_staff = role == User.Role.ADMIN
            user.is_superuser = role == User.Role.ADMIN
            user.set_password(passwords[password_name])
            user.save()
        self.stdout.write(self.style.SUCCESS("Three fictional demo logins are ready. Passwords were not displayed."))
