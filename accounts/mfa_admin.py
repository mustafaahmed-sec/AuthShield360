"""Administrator UI for portal MFA policy and Keycloak TOTP controls."""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from school.access import require_portal_admin
from school.audit import record_event

from .keycloak import KeycloakAdminError, keycloak_set_totp_required, keycloak_totp_status
from .mfa import (
    ensure_method_configuration,
    get_keycloak_mfa_policy,
    get_portal_mfa_policies,
    provider_readiness,
    role_display_name,
    save_role_policy,
)
from .mfa_forms import MFASaveConfirmationForm, RoleMFAPolicyForm
from .models import User


class KeycloakMFAPolicyForm(forms.Form):
    totp_enabled = forms.BooleanField(
        required=False, label="Require authenticator-app TOTP in Keycloak"
    )


@login_required
@require_http_methods(["GET", "POST"])
def admin_mfa_settings(request):
    require_portal_admin(request.user, request)
    policies = get_portal_mfa_policies()
    keycloak_policy = get_keycloak_mfa_policy()
    readiness = provider_readiness()
    keycloak_actual = None
    keycloak_status_error = ""
    if readiness["keycloak_admin_api"]:
        try:
            keycloak_actual = keycloak_totp_status()
        except KeycloakAdminError as error:
            keycloak_status_error = str(error)
    role_forms = {}
    for role, policy in policies.items():
        role_forms[role] = RoleMFAPolicyForm(
            request.POST if request.method == "POST" else None,
            prefix=role,
            initial={
                "enabled": policy.enabled,
                "sms_enabled": policy.sms_enabled,
                "email_enabled": policy.email_enabled,
                "require_both_factors": policy.require_both_factors,
                "include_otp_exempt_accounts": policy.include_otp_exempt_accounts,
            },
        )
    keycloak_form = KeycloakMFAPolicyForm(
        request.POST if request.method == "POST" else None,
        prefix="keycloak",
        initial={"totp_enabled": keycloak_actual if keycloak_actual is not None else keycloak_policy.totp_enabled},
    )
    confirmation = MFASaveConfirmationForm(request.POST if request.method == "POST" else None)

    if request.method == "POST":
        valid = all(form.is_valid() for form in role_forms.values())
        valid = keycloak_form.is_valid() and valid
        valid = confirmation.is_valid() and valid
        if valid:
            for role, form in role_forms.items():
                ensure_method_configuration(
                    form,
                    role,
                    sms_available=readiness["sms"],
                    email_available=readiness["email"],
                )
            valid = all(not form.errors for form in role_forms.values())
        if valid:
            requested_totp = (
                keycloak_form.cleaned_data["totp_enabled"]
                if readiness["keycloak_admin_api"]
                else keycloak_policy.totp_enabled
            )
            keycloak_changed = (
                requested_totp != keycloak_actual
                if keycloak_actual is not None
                else requested_totp != keycloak_policy.totp_enabled
            )
            if keycloak_changed and not readiness["keycloak_admin_api"]:
                keycloak_form.add_error("totp_enabled", "Keycloak Admin API is not configured; no changes were saved.")
            elif keycloak_changed and keycloak_status_error:
                keycloak_form.add_error("totp_enabled", "Keycloak flow status could not be verified; no changes were saved.")
            elif keycloak_changed and keycloak_actual is None:
                keycloak_form.add_error("totp_enabled", "The active Keycloak flow has no directly manageable OTP execution. Configure the flow first.")
            else:
                try:
                    if keycloak_changed:
                        keycloak_set_totp_required(requested_totp)
                    with transaction.atomic():
                        for role, form in role_forms.items():
                            new_values = {
                                name: form.cleaned_data[name]
                                for name in ("enabled", "sms_enabled", "email_enabled", "require_both_factors")
                            }
                            if role == User.Role.ADMIN:
                                new_values["include_otp_exempt_accounts"] = form.cleaned_data[
                                    "include_otp_exempt_accounts"
                                ]
                            old = policies[role]
                            if any(getattr(old, name) != value for name, value in new_values.items()):
                                saved = save_role_policy(role, values=new_values, actor=request.user)
                                methods = [
                                    label for name, label in (
                                        ("sms_enabled", "Firebase SMS"),
                                        ("email_enabled", "Email OTP"),
                                    ) if getattr(saved, name)
                                ]
                                record_event(
                                    request.user,
                                    "mfa_policy_updated",
                                    f"Role MFA {'enabled' if saved.enabled else 'disabled'}; methods: {', '.join(methods) if methods else 'none'}; both factors: {'required' if saved.require_both_factors else 'not required'}.",
                                    target_name=role_display_name(role),
                                    request=request,
                                    factor="access",
                                    outcome="success",
                                )
                        if keycloak_changed or keycloak_policy.totp_enabled != requested_totp:
                            keycloak_policy.totp_enabled = requested_totp
                            keycloak_policy.updated_by = request.user
                            keycloak_policy.save(update_fields=("totp_enabled", "updated_at", "updated_by"))
                            record_event(
                                request.user,
                                "keycloak_mfa_updated",
                                f"Keycloak authenticator-app TOTP was {'enabled' if requested_totp else 'disabled'} in the active browser flow.",
                                target_name="Keycloak TOTP",
                                request=request,
                                factor="access",
                                outcome="success",
                            )
                except KeycloakAdminError as error:
                    keycloak_form.add_error("totp_enabled", f"Keycloak rejected the change: {error}")
                else:
                    if not keycloak_form.errors:
                        messages.success(
                            request,
                            "MFA settings were saved. Pending portal OTP sign-ins for changed roles were invalidated; active sessions remain signed in.",
                        )
                        return redirect("admin_mfa_settings")

    return render(request, "school/admin_mfa_settings.html", {
        "role_forms": role_forms,
        "role_values": list(role_forms),
        "role_labels": {role: role_display_name(role) for role in role_forms},
        "role_sections": [
            {"role": role, "label": role_display_name(role), "form": form}
            for role, form in role_forms.items()
        ],
        "keycloak_form": keycloak_form,
        "confirmation_form": confirmation,
        "readiness": readiness,
        "keycloak_actual": keycloak_actual,
        "keycloak_status_error": keycloak_status_error,
        "keycloak_manage_available": readiness["keycloak_admin_api"] and keycloak_actual is not None and not keycloak_status_error,
    })
