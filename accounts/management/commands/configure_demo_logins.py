"""Prepare local fictional logins from secrets held in the ignored .env file."""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
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
        User = get_user_model()
        role_by_name = {
            "DEMO_STUDENT_PASSWORD": User.Role.STUDENT,
            "DEMO_TEACHER_PASSWORD": User.Role.TEACHER,
            "DEMO_ADMIN_PASSWORD": User.Role.ADMIN,
        }
        try:
            for name, value in passwords.items():
                validate_password(value, user=User(role=role_by_name[name]))
        except ValidationError as error:
            raise CommandError(
                "Each DEMO_*_PASSWORD in the ignored .env file must be 12–50 characters "
                "(at least 25 for the Administrator) and include lowercase, uppercase, "
                "a number, and a special character."
            ) from error

        accounts = (
            ("ali.khan.authshield@gmail.com", "Ali Khan", User.Role.STUDENT, "DEMO_STUDENT_PASSWORD"),
            ("sara.ahmed.authshield@gmail.com", "Sara Ahmed", User.Role.TEACHER, "DEMO_TEACHER_PASSWORD"),
            ("mina.rahman.authshield@gmail.com", "Mina Rahman", User.Role.ADMIN, "DEMO_ADMIN_PASSWORD"),
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
