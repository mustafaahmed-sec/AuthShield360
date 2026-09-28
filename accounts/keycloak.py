"""Keycloak OpenID Connect client used by the portal's server-side login flow."""

from urllib.parse import quote

from authlib.integrations.django_client import OAuth
import requests

from django.conf import settings


class KeycloakAdminError(Exception):
    """Raised when a server-side Keycloak administrator operation is unavailable."""


def keycloak_client():
    if not settings.AUTHSHIELD_KEYCLOAK_ENABLED:
        return None

    oauth = OAuth()
    oauth.register(
        name="keycloak",
        client_id=settings.AUTHSHIELD_KEYCLOAK_CLIENT_ID,
        client_secret=settings.AUTHSHIELD_KEYCLOAK_CLIENT_SECRET,
        server_metadata_url=f"{settings.AUTHSHIELD_KEYCLOAK_ISSUER}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email"},
    )
    return oauth.create_client("keycloak")


def keycloak_admin_request(method, resource, *, payload=None):
    if not settings.AUTHSHIELD_KEYCLOAK_ENABLED or not settings.AUTHSHIELD_KEYCLOAK_ADMIN_API_ENABLED:
        raise KeycloakAdminError("Keycloak administrator API credentials are not configured.")

    token_url = f"{settings.AUTHSHIELD_KEYCLOAK_ISSUER}/protocol/openid-connect/token"
    admin_base = (
        f"{settings.AUTHSHIELD_KEYCLOAK_SERVER_URL}/admin/realms/"
        f"{quote(settings.AUTHSHIELD_KEYCLOAK_REALM, safe='')}"
    )
    try:
        token_response = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_ID,
                "client_secret": settings.AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_SECRET,
            },
            timeout=(3, 8),
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        response = requests.request(
            method,
            f"{admin_base}/{resource.lstrip('/')}",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
            timeout=(3, 8),
        )
        response.raise_for_status()
        return response
    except (requests.RequestException, KeyError, ValueError) as error:
        raise KeycloakAdminError(type(error).__name__) from None


def keycloak_set_user_enabled(subject, enabled):
    return keycloak_admin_request(
        "PUT",
        f"users/{quote(subject, safe='')}",
        payload={"enabled": bool(enabled)},
    )


def keycloak_clear_user_login_failures(subject):
    return keycloak_admin_request(
        "DELETE",
        f"attack-detection/brute-force/users/{quote(subject, safe='')}",
    )


def keycloak_delete_user(subject):
    return keycloak_admin_request("DELETE", f"users/{quote(subject, safe='')}")


def keycloak_reset_user_password(subject, password):
    return keycloak_admin_request(
        "PUT",
        f"users/{quote(subject, safe='')}/reset-password",
        payload={"type": "password", "value": password, "temporary": True},
    )


def keycloak_send_password_reset(subject):
    return keycloak_admin_request(
        "PUT",
        f"users/{quote(subject, safe='')}/execute-actions-email",
        payload=["UPDATE_PASSWORD"],
    )
