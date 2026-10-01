# AuthShield 360 — Project README and Handoff Guide

- **Prepared:** 1 October 2026
- **Audience:** Project reviewers, maintainers, and the next administrator

AuthShield 360 is a fictional school portal created for an identity-security demonstration. It provides separate Student, Teacher, and Administrator experiences, account approval, school records, audit events, password protections, and multi-factor sign-in.

## At a glance

The application uses Python and Django. PostgreSQL stores portal data; the documented production database is hosted on Neon. Vercel hosts the portal web application. Firebase Authentication supplies browser-based phone verification and SMS delivery. Django's configured email backend sends email codes. GitHub holds the source and workflow checks.

This USB copy includes the source tree, this handoff guide, and restricted portal-access materials. It does not include production deployment settings, Vercel project-link metadata, Neon credentials, or a database backup. Copying the folder does not transfer cloud account ownership.

## How the parts connect

- Browser → Django portal on Vercel → PostgreSQL on Neon
- Browser → Firebase Phone Authentication → reCAPTCHA and SMS verification
- Django → Firebase token verification → validates the signed phone result
- Django → configured SMTP/email backend → email OTP and account messages
- GitHub → source and automated checks → Vercel deployment
- Optional: browser → Keycloak OIDC → Django callback → portal role, approval, and MFA checks

The source contains an optional Keycloak integration, but its current documentation and default configuration describe Keycloak sign-in as disabled. The hosted provider setting must be checked in Vercel to establish the live state. Keycloak OIDC and authenticator-app TOTP are separate from Firebase SMS and portal email OTP.

## Technology responsibilities

| Component | Role |
| --- | --- |
| Django and Python | Pages, validation, authentication, permissions, OTP challenges, audit events, and application logic |
| PostgreSQL / Neon | Persistent portal accounts and school records |
| Firebase Authentication | Browser reCAPTCHA and phone/SMS verification, with a signed ID token returned to the portal |
| SMTP / Django email backend | Email verification codes and account messages |
| Vercel | Portal hosting |
| GitHub | Source control and automation |
| Keycloak | Optional OIDC identity provider and separate optional authenticator-app TOTP |

## Source map

- **accounts/**: user model, login, registration requests, approval, email OTP, Firebase token validation, lockouts, MFA policy, Keycloak integration, and authentication audit records.
- **school/**: Student, Teacher, and Administrator views; courses, enrollment, assignments, results, attendance, account management, and dashboards.
- **config/**: Django settings, routes, WSGI entry point, and test settings.
- **templates/**: authentication, dashboard, and school workflow pages.
- **static/**: CSS, images, and browser JavaScript, including Firebase phone verification.
- **README.md**: the single project guide, setup instructions, and system overview.
- **.github/**: repository workflow configuration.
- **keycloak-vercel/**: optional Keycloak material; its presence does not prove a public Keycloak server is running.

## Roles and account approval

- **Students** can see their own permitted profile, course, assignment, result, and attendance information.
- **Teachers** work with assigned courses and the students in those classes.
- **Administrators** review access requests, manage portal accounts, use account-lockout controls, review audit activity, and administer school data.

Student and Teacher sign-ups start as pending access requests. An Administrator must approve them before portal access is granted. Portal roles and school approval remain Django responsibilities even if an external identity provider is configured.

## Sign-in flow, end to end

When both OTP providers are available, the current code follows the SRS sign-in order for Student, Teacher, and Administrator accounts: password, Firebase SMS verification, then email OTP.

1. The person submits a portal email and password.
2. Django checks the password, account status, approval, failed-login count, and active lockout.
3. The browser completes Firebase Phone Auth. Its reCAPTCHA check must succeed before Firebase accepts an SMS send request.
4. The user enters the SMS code. Firebase confirms it and returns a signed ID token to the browser.
5. The browser sends that token to Django. Django verifies it against the configured Firebase project and checks that it represents a fresh phone verification for the phone saved on that account.
6. Django creates a database-backed email challenge and sends the code through the configured email backend. The code is stored as a hash, has a purpose and expiry, and is checked for use and attempt limits.
7. The user enters the email code in the portal. A valid code advances the flow.
8. Only after the required factors and account checks succeed does Django create the portal session and route the person to the correct role dashboard.

The email code and SMS code are separate verification channels. The password is a knowledge factor; email and SMS are possession channels. A visible “sent” message or a typed six-digit value by itself is not sufficient evidence of successful phone verification; Django requires Firebase's signed token.

Password recovery uses a separate email challenge purpose. Student and Teacher account requests are not the same as approved sign-in accounts. Request status and approval are checked separately from the ordinary login flow.

## MFA management and Keycloak

The portal MFA page is located at **Administrator Dashboard → Security → MFA Settings**, route **/administrator/security/mfa/**. It is intended for authorized administrators. The UI stores role policy records and audits changes. Current sign-in decisions in accounts/mfa.py derive the effective channels from provider readiness. If email and Firebase are both ready, every role is required to use both factors, SMS first and email second. The form also prevents disabling that required combination. The page therefore does not currently provide independent per-role switches that can relax the actual login flow while both providers are configured.

Changing a saved role policy invalidates affected pending sign-in codes. It does not end existing authenticated sessions or invalidate password-reset challenges. A future enhancement would be to make the policy saved for each role the direct source of sign-in decisions, while preserving a safe recovery path and audit trail.

Keycloak TOTP is an authenticator-app code, not an SMS. Keycloak becomes part of login only when its server and OIDC configuration are enabled and reachable. The project code can continue portal OTP checks after a Keycloak identity callback; the integration does not make Keycloak send Firebase SMS.

## OTP limits and lockouts

These are documented source defaults. A deployment may override them, so verify actual provider environment values before treating them as live settings.

| Control | Default described by the project |
| --- | --- |
| Email OTP lifetime | 5 minutes |
| SMS challenge lifetime | 5 minutes |
| Password-reset code lifetime | 5 minutes |
| Wait between sign-in code requests | 5 minutes |
| Sign-in code sends | 3 per account/channel limit window |
| Send lock after reaching the ceiling | 30 minutes |
| Incorrect code attempts | Up to 5 before the applicable challenge/account limit is enforced |
| Password failures | 5 failures in 15 minutes trigger a 5-minute account lock |
| Repeated password lockouts | Escalate to 15 minutes, then 30 minutes during the repeat-lock period |
| Password-recovery requests | Default 30 per observed IP in 15 minutes |

Firebase has its own quotas, abuse controls, region rules, and SMS charges. Portal limits reduce unnecessary requests but cannot override Firebase or guarantee carrier delivery. An administrator resetting a portal lockout does not remove Firebase-side restrictions.

## Audit and security boundaries

The code includes role checks, approval gating, failed-password lockouts, OTP expiry and attempt limits, resend controls, session handling, audit events, and server-side Firebase token verification. Audit events are designed to avoid recording passwords, readable OTPs, or raw session cookies.

These are security controls, not proof that a system is unhackable. Automated application tests do not certify provider settings, every production route, every browser, or every possible attack. This USB copy does not include a completed ZAP/Burp assessment or a complete record of hosted and manual SRS evidence. It makes no claim of a completed penetration test or vulnerability-free status.

## Configuration and secrets

The names of expected settings are listed in **.env.example**. The main groups are:

- Django: DJANGO_SECRET_KEY, DJANGO_DEBUG, DJANGO_ALLOWED_HOSTS.
- Database: DATABASE_URL or the DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT group.
- Portal login: AUTHSHIELD_BASELINE_LOGIN, AUTHSHIELD_OTP_ENABLED, AUTHSHIELD_EMAIL_STEP_UP, and lockout settings.
- OTP timing: AUTHSHIELD_EMAIL_OTP_TTL_SECONDS, AUTHSHIELD_SMS_OTP_TTL_SECONDS, AUTHSHIELD_OTP_RESEND_COOLDOWN_SECONDS, AUTHSHIELD_OTP_MAX_SENDS, AUTHSHIELD_OTP_SEND_LOCKOUT_MINUTES.
- Email delivery: AUTHSHIELD_GMAIL_ADDRESS and AUTHSHIELD_GMAIL_APP_PASSWORD.
- Firebase web configuration: AUTHSHIELD_FIREBASE_API_KEY, AUTHSHIELD_FIREBASE_AUTH_DOMAIN, AUTHSHIELD_FIREBASE_PROJECT_ID, AUTHSHIELD_FIREBASE_APP_ID.
- Optional Keycloak: AUTHSHIELD_KEYCLOAK_ENABLED and its server, realm, client, and secret settings.

The USB includes **Portal Role Credentials.txt** and **AuthShield Access Directory.xlsx** for the authorized portal administrator. They may contain readable account details, are excluded from Git and Vercel uploads, and should be kept under the administrator's control. The USB contains `.env.example` as a setup template, but no `.env`, `.env.production.local`, or Vercel project-link metadata. Machine-specific local settings and production deployment configuration are kept separately on the maintainer's PC; `.env.production.local` is not read automatically by Django. Vercel production variables and Neon access remain managed through their provider accounts, whose permissions must be granted separately.

This guide lists setting names only. It does not include credential values. Keep private keys, SMTP passwords, database URLs, and client secrets out of public repositories, screenshots, blogs, and ordinary email. If the USB or workbook is lost or exposed, revoke or rotate affected credentials promptly.

## Local setup and deployment

### Local Windows setup (fictional demonstration data only)

Prerequisites: Python 3.12 or newer, PostgreSQL 17 with pgAdmin 4, and a modern browser.

1. In pgAdmin, create a dedicated local database login role and a local database named authshield360. Give the application role only the permissions needed for this database; do not connect as the PostgreSQL superuser.
2. Create a private .env from .env.example. Set a fresh Django secret and a local database connection. Add provider settings only for services you intentionally configure. Do not copy production credentials into the demo environment, commit .env, or send it to an evaluator.
3. From the project folder, run these commands in PowerShell:

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe manage.py migrate
    .\.venv\Scripts\python.exe manage.py seed_demo
    .\.venv\Scripts\python.exe manage.py configure_demo_logins
    .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000

4. Open http://127.0.0.1:8000/ for the portal. Student and Teacher requests are submitted at /signup/student/ and /signup/teacher/. They remain pending until approved. The status page is /signup/status/.
5. Run automated checks with:

    .\.venv\Scripts\python.exe manage.py test --settings=config.test_settings --noinput
    .\.venv\Scripts\ruff.exe check accounts config school
    .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.test_settings

Use the isolated test settings for tests. Seed, reset, and cleanup commands belong only on a disposable local demonstration database. Never run them against production or real school data.

The project’s fictional demo login credentials are not repeated in this public-facing guide. Use the private access materials only if you are authorized to do so.

Never run demo seed, reset, or cleanup commands against production or real school data.

The project documentation describes Vercel as the portal host and Neon as the production database. A GitHub push triggers deployment only when the repository is connected to the intended Vercel project. A successful build or public landing page alone does not prove that the complete authenticated flow works.

The hosted database and provider accounts remain online and are not transferred by copying this folder. A new operator needs authorized access to Vercel, Neon, Firebase, email delivery, GitHub, and Keycloak if that optional service is used.

## Verification status

On 1 October 2026, the full Django test suite passed 136 tests under isolated SQLite test settings. Ruff passed, and Django reported no migration drift. The tests exercised the new OTP delivery-limit migration in the isolated test database. These code checks do not apply migrations to or inspect the hosted database.

The project owner and team have reported successful OTP sign-ins for Student, Teacher, and Administrator accounts. That is team-reported live evidence; this code-only review did not request an OTP or repeat a hosted login.

The detailed SRS evidence pack and dated supporting records were removed from this USB copy at the owner’s request. No formal penetration-test report, complete hosted performance/persistence record, browser/accessibility review, or demo video is included here. Treat those items as unverified unless separate evidence is provided.

## Troubleshooting

- **SMS does not arrive:** check Firebase Phone Auth, the authorized deployed domain, reCAPTCHA completion, the account phone in international form, allowed destination regions, Firebase billing, and provider throttling.
- **Firebase reports a send error:** use the exact Firebase error in the browser and provider console. A portal timer does not prove Firebase accepted the send.
- **Email code is delayed:** verify the account email, server-side email configuration, spam folder, and deployment logs. Never ask the user for their mailbox password.
- **Only one factor appears:** check provider readiness, account enrollment, the current role policy, and deployed environment configuration.
- **A correct password is rejected:** check pending approval, account role, lockout status, and whether the person is using request-status rather than login.
- **Keycloak is absent or unreachable:** check server-side enablement and a reachable realm. Having Keycloak files or a downloaded ZIP is not the same as running an identity server.
- **Local works but hosted does not:** compare environment configuration privately, database migrations, allowed domains, and provider logs. Do not paste secrets into support tickets.

## USB handoff

This is a source-folder handoff, not a transfer of cloud ownership or a database backup. Keep the USB and its readable local credentials with the intended administrator; do not upload them to GitHub or Vercel, or send them through an unprotected channel. Another maintainer still needs to be granted access to GitHub, Vercel, Neon, Firebase, email delivery, and Keycloak if used. Consider rotating credentials after transfer if the USB was accessible to anyone else.

## Project documents

This README is the project’s single Markdown handoff guide. The private beginner and jury study guide is at **output/pdf/AuthShield360_TechViz_Study_Guide.pdf**. Use it alongside this README to understand the system and prepare for a project demonstration.
