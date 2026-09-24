"""Isolated SQLite settings for the repeatable automated test suite."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "authshield-isolated-test-key-never-use-in-production")

from .settings import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1", "authshield360.vercel.app"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
AUTHSHIELD_BASELINE_LOGIN_ENABLED = True
AUTHSHIELD_PROTECTED_DEMO = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
