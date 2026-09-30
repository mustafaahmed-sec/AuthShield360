"""Local-first Django settings for the AuthShield 360 lab."""

import os
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if host.strip()]
AUTHSHIELD_SCHOOLWIDE_TEACHER_EMAIL = os.environ.get(
    "AUTHSHIELD_SCHOOLWIDE_TEACHER_EMAIL", "sara.ahmed.authshield@gmail.com"
).strip().lower()
for deployment_host in (
    os.environ.get("VERCEL_URL"),
    os.environ.get("VERCEL_PROJECT_PRODUCTION_URL"),
    os.environ.get("RENDER_EXTERNAL_HOSTNAME"),
):
    if deployment_host and deployment_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(deployment_host)

CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host != "localhost" and host != "127.0.0.1"]
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

INSTALLED_APPS = [
    "config.admin.AuthShieldAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "school",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.CanonicalProductionHostMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.middleware.MustChangePasswordMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.static_version",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"


def _same_database_target(left_url, right_url):
    left = urlparse(left_url)
    right = urlparse(right_url)
    return (
        (left.hostname or "").lower().replace("-pooler.", ".")
        == (right.hostname or "").lower().replace("-pooler.", ".")
        and (left.port or 5432) == (right.port or 5432)
        and left.path.rstrip("/").lower() == right.path.rstrip("/").lower()
    )


AUTHSHIELD_STAGING_MODE = os.environ.get("AUTHSHIELD_STAGING_MODE", "false").lower() == "true"
vercel_environment = os.environ.get("VERCEL_ENV", "").lower()
if vercel_environment == "preview" and not AUTHSHIELD_STAGING_MODE:
    raise ImproperlyConfigured(
        "Vercel Preview requires AUTHSHIELD_STAGING_MODE and a separate STAGING_DATABASE_URL."
    )
if AUTHSHIELD_STAGING_MODE:
    if vercel_environment != "preview":
        raise ImproperlyConfigured("AUTHSHIELD_STAGING_MODE is allowed only in Vercel Preview deployments.")
    database_url = os.environ.get("STAGING_DATABASE_URL")
    if not database_url:
        raise ImproperlyConfigured("STAGING_DATABASE_URL is required for a staging Preview deployment.")
    production_database_url = os.environ.get("DATABASE_URL")
    if production_database_url and _same_database_target(database_url, production_database_url):
        raise ImproperlyConfigured("STAGING_DATABASE_URL must point to a database separate from production.")
else:
    database_url = os.environ.get("DATABASE_URL")

if database_url:
    parsed_database_url = urlparse(database_url)
    if parsed_database_url.scheme not in ("postgres", "postgresql") or not parsed_database_url.hostname:
        raise ImproperlyConfigured("DATABASE_URL must be a PostgreSQL connection URL.")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed_database_url.path.lstrip("/")),
            "USER": unquote(parsed_database_url.username or ""),
            "PASSWORD": unquote(parsed_database_url.password or ""),
            "HOST": parsed_database_url.hostname,
            "PORT": parsed_database_url.port or 5432,
            "OPTIONS": {"sslmode": "require"},
            "CONN_MAX_AGE": 0,
        }
    }
else:
    if os.environ.get("VERCEL") or not DEBUG:
        raise ImproperlyConfigured("A PostgreSQL DATABASE_URL is required for hosted or non-debug deployments.")
    if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        raise ImproperlyConfigured("A hosted DATABASE_URL is required on Render.")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "authshield360"),
            "USER": os.environ.get("DB_USER", "authshield_app"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "accounts.validators.RoleBasedPasswordMinimumLengthValidator", "OPTIONS": {"min_length": 12, "admin_min_length": 25}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "accounts.validators.PasswordCharacterSetValidator"},
    {"NAME": "accounts.validators.PasswordMaximumLengthValidator", "OPTIONS": {"max_length": 50}},
]

LANGUAGE_CODE = "en-us"
# Keep audit events and portal-facing dates in the school's Pakistan time zone.
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"
SESSION_COOKIE_AGE = 900
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"


def _positive_integer_setting(name, default):
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} must be a positive integer.") from error
    if value <= 0:
        raise ImproperlyConfigured(f"{name} must be a positive integer.")
    return value


AUTHSHIELD_LOCKOUT_ATTEMPTS = _positive_integer_setting("AUTHSHIELD_LOCKOUT_ATTEMPTS", 5)
AUTHSHIELD_LOCKOUT_WINDOW_MINUTES = _positive_integer_setting("AUTHSHIELD_LOCKOUT_WINDOW_MINUTES", 15)
AUTHSHIELD_LOCKOUT_MINUTES = _positive_integer_setting("AUTHSHIELD_LOCKOUT_MINUTES", 5)
AUTHSHIELD_IP_FAILURE_LIMIT = _positive_integer_setting("AUTHSHIELD_IP_FAILURE_LIMIT", 30)
AUTHSHIELD_IP_WINDOW_MINUTES = _positive_integer_setting("AUTHSHIELD_IP_WINDOW_MINUTES", 15)
AUTHSHIELD_IP_THROTTLE_MINUTES = _positive_integer_setting("AUTHSHIELD_IP_THROTTLE_MINUTES", 1)
AUTHSHIELD_OTP_TTL_SECONDS = _positive_integer_setting("AUTHSHIELD_OTP_TTL_SECONDS", 600)
AUTHSHIELD_SMS_OTP_TTL_SECONDS = _positive_integer_setting("AUTHSHIELD_SMS_OTP_TTL_SECONDS", 300)
AUTHSHIELD_SMS_OTP_ACCOUNT_LIMIT = _positive_integer_setting("AUTHSHIELD_SMS_OTP_ACCOUNT_LIMIT", 4)
AUTHSHIELD_SMS_OTP_ACCOUNT_WINDOW_MINUTES = _positive_integer_setting(
    "AUTHSHIELD_SMS_OTP_ACCOUNT_WINDOW_MINUTES", 15
)
AUTHSHIELD_EMAIL_OTP_TTL_SECONDS = _positive_integer_setting("AUTHSHIELD_EMAIL_OTP_TTL_SECONDS", 60)
AUTHSHIELD_PASSWORD_RESET_OTP_TTL_SECONDS = _positive_integer_setting("AUTHSHIELD_PASSWORD_RESET_OTP_TTL_SECONDS", 300)
AUTHSHIELD_PASSWORD_RESET_IP_LIMIT = _positive_integer_setting("AUTHSHIELD_PASSWORD_RESET_IP_LIMIT", 30)
AUTHSHIELD_PASSWORD_RESET_IP_WINDOW_MINUTES = _positive_integer_setting(
    "AUTHSHIELD_PASSWORD_RESET_IP_WINDOW_MINUTES", 15
)
AUTHSHIELD_PASSWORD_RESET_RESPONSE_FLOOR_SECONDS = _positive_integer_setting(
    "AUTHSHIELD_PASSWORD_RESET_RESPONSE_FLOOR_SECONDS", 9
)
AUTHSHIELD_SIGNUP_IP_LIMIT = _positive_integer_setting("AUTHSHIELD_SIGNUP_IP_LIMIT", 10)
AUTHSHIELD_SIGNUP_IP_WINDOW_MINUTES = _positive_integer_setting("AUTHSHIELD_SIGNUP_IP_WINDOW_MINUTES", 15)
AUTHSHIELD_BLOCKED_AUDIT_LIMIT = _positive_integer_setting("AUTHSHIELD_BLOCKED_AUDIT_LIMIT", 5)
AUTHSHIELD_BLOCKED_AUDIT_WINDOW_MINUTES = _positive_integer_setting(
    "AUTHSHIELD_BLOCKED_AUDIT_WINDOW_MINUTES", 15
)

# Password-only access remains a controlled lab stage. For a Vercel demo it
# requires a separately configured protected deployment; ordinary users never
# choose the authentication mode from the portal.
AUTHSHIELD_PROTECTED_DEMO = os.environ.get("AUTHSHIELD_PROTECTED_DEMO", "false").lower() == "true"
AUTHSHIELD_KEYCLOAK_ENABLED = os.environ.get("AUTHSHIELD_KEYCLOAK_ENABLED", "false").lower() == "true"
AUTHSHIELD_BASELINE_LOGIN_ENABLED = (
    os.environ.get("AUTHSHIELD_BASELINE_LOGIN", "false").lower() == "true"
    and (DEBUG or AUTHSHIELD_PROTECTED_DEMO)
)
AUTHSHIELD_OTP_ENABLED = os.environ.get("AUTHSHIELD_OTP_ENABLED", "false").lower() == "true"
AUTHSHIELD_KEYCLOAK_SERVER_URL = os.environ.get("AUTHSHIELD_KEYCLOAK_SERVER_URL", "").strip().rstrip("/")
AUTHSHIELD_KEYCLOAK_REALM = os.environ.get("AUTHSHIELD_KEYCLOAK_REALM", "").strip()
AUTHSHIELD_KEYCLOAK_CLIENT_ID = os.environ.get("AUTHSHIELD_KEYCLOAK_CLIENT_ID", "").strip()
AUTHSHIELD_KEYCLOAK_CLIENT_SECRET = os.environ.get("AUTHSHIELD_KEYCLOAK_CLIENT_SECRET", "").strip()
AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_ID = os.environ.get("AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_ID", "").strip()
AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_SECRET = os.environ.get("AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_SECRET", "").strip()
AUTHSHIELD_KEYCLOAK_ADMIN_API_ENABLED = bool(
    AUTHSHIELD_KEYCLOAK_ENABLED
    and AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_ID
    and AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_SECRET
)
AUTHSHIELD_KEYCLOAK_ISSUER = (
    f"{AUTHSHIELD_KEYCLOAK_SERVER_URL}/realms/{quote(AUTHSHIELD_KEYCLOAK_REALM, safe='')}"
    if AUTHSHIELD_KEYCLOAK_SERVER_URL and AUTHSHIELD_KEYCLOAK_REALM
    else ""
)
AUTHSHIELD_KEYCLOAK_ADMIN_CONSOLE_URL = (
    f"{AUTHSHIELD_KEYCLOAK_SERVER_URL}/admin/{quote(AUTHSHIELD_KEYCLOAK_REALM, safe='')}/console/"
    if AUTHSHIELD_KEYCLOAK_SERVER_URL and AUTHSHIELD_KEYCLOAK_REALM
    else ""
)
if AUTHSHIELD_KEYCLOAK_ENABLED and not all((
    AUTHSHIELD_KEYCLOAK_ISSUER,
    AUTHSHIELD_KEYCLOAK_CLIENT_ID,
    AUTHSHIELD_KEYCLOAK_CLIENT_SECRET,
)):
    raise ImproperlyConfigured(
        "Keycloak sign-in is enabled but its server URL, realm, client ID, or client secret is missing."
    )
if AUTHSHIELD_KEYCLOAK_ENABLED and not DEBUG and urlparse(AUTHSHIELD_KEYCLOAK_SERVER_URL).scheme != "https":
    raise ImproperlyConfigured("Keycloak must use an HTTPS server URL outside local development.")
AUTHSHIELD_OTP_EXEMPT_EMAILS = frozenset(
    email.strip().lower()
    for email in os.environ.get("AUTHSHIELD_OTP_EXEMPT_EMAILS", "").split(",")
    if email.strip()
)
AUTHSHIELD_LOGIN_ENABLED = (
    (AUTHSHIELD_BASELINE_LOGIN_ENABLED or AUTHSHIELD_OTP_ENABLED or AUTHSHIELD_KEYCLOAK_ENABLED)
    and (DEBUG or AUTHSHIELD_PROTECTED_DEMO)
)
AUTHSHIELD_EMAIL_STEP_UP = os.environ.get("AUTHSHIELD_EMAIL_STEP_UP", "false").lower() == "true"
AUTHSHIELD_GMAIL_ADDRESS = os.environ.get("AUTHSHIELD_GMAIL_ADDRESS", "").strip()
AUTHSHIELD_GMAIL_APP_PASSWORD = "".join(os.environ.get("AUTHSHIELD_GMAIL_APP_PASSWORD", "").split())
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
EMAIL_TIMEOUT = 8
EMAIL_HOST_USER = AUTHSHIELD_GMAIL_ADDRESS
EMAIL_HOST_PASSWORD = AUTHSHIELD_GMAIL_APP_PASSWORD
DEFAULT_FROM_EMAIL = AUTHSHIELD_GMAIL_ADDRESS
AUTHSHIELD_FIREBASE_API_KEY = os.environ.get("AUTHSHIELD_FIREBASE_API_KEY", "").strip()
AUTHSHIELD_FIREBASE_AUTH_DOMAIN = os.environ.get("AUTHSHIELD_FIREBASE_AUTH_DOMAIN", "").strip()
AUTHSHIELD_FIREBASE_PROJECT_ID = os.environ.get("AUTHSHIELD_FIREBASE_PROJECT_ID", "").strip()
AUTHSHIELD_FIREBASE_APP_ID = os.environ.get("AUTHSHIELD_FIREBASE_APP_ID", "").strip()
if AUTHSHIELD_KEYCLOAK_ENABLED and not AUTHSHIELD_OTP_ENABLED:
    raise ImproperlyConfigured("Enable AuthShield OTP before switching the portal to Keycloak sign-in.")
if AUTHSHIELD_KEYCLOAK_ENABLED and not all((
    AUTHSHIELD_FIREBASE_API_KEY,
    AUTHSHIELD_FIREBASE_AUTH_DOMAIN,
    AUTHSHIELD_FIREBASE_PROJECT_ID,
    AUTHSHIELD_FIREBASE_APP_ID,
)):
    raise ImproperlyConfigured("Keycloak sign-in requires the Firebase Phone Auth web-app configuration.")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "portal": {"format": "%(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "portal"},
    },
    "loggers": {
        "authshield": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
