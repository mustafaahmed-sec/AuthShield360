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


def _keycloak_browser_flow():
    """Return the active browser flow and its top-level OTP execution, if safe."""
    realm = keycloak_admin_request("GET", "")
    browser_alias = realm.json().get("browserFlow")
    if not browser_alias:
        raise KeycloakAdminError("The active Keycloak browser flow could not be identified.")
    executions_response = keycloak_admin_request(
        "GET", f"authentication/flows/{quote(browser_alias, safe='')}/executions"
    )
    executions = executions_response.json()
    if not isinstance(executions, list):
        raise KeycloakAdminError("Keycloak returned an unsupported browser-flow configuration.")
    otp_execution = next(
        (item for item in executions if item.get("providerId") == "auth-otp-form"),
        None,
    )
    return browser_alias, otp_execution


def keycloak_totp_status():
    """Inspect the active flow. None means no directly managed OTP execution exists."""
    _, execution = _keycloak_browser_flow()
    if not execution:
        return None
    return execution.get("requirement") == "REQUIRED"


def keycloak_set_totp_required(enabled):
    """Set OTP only when an unconditional execution exists in the active browser flow.

    Nested conditional flows require separate review because marking their execution
    required could leave users without an enrolled authenticator able to bypass MFA.
    """
    alias, execution = _keycloak_browser_flow()
    if not execution:
        raise KeycloakAdminError(
            "No OTP authenticator execution exists in the active Keycloak browser flow."
        )
    if execution.get("level", 0) not in (0, "0") or execution.get("authenticationFlow"):
        raise KeycloakAdminError(
            "The OTP execution is inside a subflow. Configure and review an unconditional portal OTP execution first."
        )
    updated = dict(execution)
    updated["requirement"] = "REQUIRED" if enabled else "DISABLED"
    keycloak_admin_request(
        "PUT",
        f"authentication/flows/{quote(alias, safe='')}/executions",
        payload=updated,
    )
