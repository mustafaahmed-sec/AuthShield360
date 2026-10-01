# AuthShield 360

**A school portal with role-based access and multi-factor sign-in**<br>
TechViz competition, hosted by Aptech<br>
MSG Security Squad | Mentor: Sir Anas
Team leader: Mustafa Ahmed | Team: Munniba, Aliyan, Mehak, Aisha, Rabia

Prepared 1 October 2026. This README is the single Markdown handoff guide for the project.

## What the project does

AuthShield 360 is a Django school portal for Students, Teachers, and Administrators. It handles account requests and approvals, role-specific dashboards, class records, attendance, assignments, results, and security audit events. The login flow can require a password followed by Firebase SMS verification and an email code.

The project was built for the TechViz competition hosted by Aptech. It demonstrates how an application can connect identity checks to school workflows and protect those workflows with role permissions.

## Handoff contents

The repository root is the **source code**. The project does not need a second nested copy of its source.

```text
AuthShield360/
├── accounts/             Authentication, account requests, MFA, OTP and migrations
├── school/               School workflows, permissions, audit and migrations
├── config/               Django settings, routes and deployment entry points
├── templates/            Portal pages
├── static/               CSS, browser scripts and AuthShield artwork
├── Documentation/        One study guide PDF and one editable jury presentation
├── Database/             ER diagram and database setup handoff
├── keycloak-vercel/      Optional Keycloak service source; not proof of a live server
├── .github/workflows/    Automated code checks
├── LIVE_LINK.txt         Recorded portal and source links
├── manage.py             Django management command
└── README.md             This handoff guide
```

There is no `VIDEO` folder because no video was supplied. There is no `APK` folder because this project is a web portal, not an Android application. The private workbook and `Portal Role Credentials.txt` are present only in the C: and USB copies. Git ignores both, and `.vercelignore` excludes them from deployment packaging. Do not upload them to GitHub, Vercel, or an unprotected shared drive.

The public portal URL recorded for the project is `https://authshield360.vercel.app`. The GitHub source is `https://github.com/mustafaahmed-sec/AuthShield360`. The URL is a handoff reference; this review did not verify the current Vercel deployment or sign in to it.

## Architecture and service roles

| Part | What it does |
| --- | --- |
| Django and Python | Serves pages, checks passwords, enforces roles, stores OTP challenges, and records application events. |
| PostgreSQL on Neon | Stores portal accounts, school records, policy settings, quotas, and audit events. Django migrations define the schema. |
| Firebase Authentication | Runs browser phone verification, including reCAPTCHA and SMS. The browser receives a signed Firebase token that Django verifies. |
| Django email backend | Sends email OTPs and account messages. It is configured with deployment environment settings. |
| Vercel | Hosts the web application and runs its server-side code. Documentation and database diagrams are excluded from Vercel packaging. |
| GitHub | Holds tracked source and runs the repository checks on pushes and pull requests. |
| Keycloak, optional | Can provide OIDC sign-in and authenticator-app TOTP when its server and Admin API are configured. It does not send the Firebase SMS. |

```text
Person's browser
   ├── Django portal on Vercel ─── PostgreSQL database on Neon
   │       ├── configured email service ─── email OTP
   │       └── verifies Firebase ID token
   ├── Firebase Phone Auth ─── reCAPTCHA and SMS carrier
   └── optional Keycloak OIDC sign-in

GitHub source and checks ─── connected Vercel project, if configured
```

The normal portal MFA path is **password, SMS OTP, email OTP** when both factors are enabled and available. Keycloak's optional authenticator-app TOTP is separate. Files under `keycloak-vercel/` are source/configuration material; they do not demonstrate that the identity server is currently running or reachable.

## Login, request status, and recovery

### Password and SMS first, then email

1. The user enters the email and password used for the portal account.
2. Django checks the password, account approval, role, failed-login state, and lockout.
3. The browser must pass Firebase reCAPTCHA before it requests SMS.
4. Firebase sends a code to the registered phone when the provider accepts the request. The user enters that code in the portal.
5. Firebase returns a signed ID token after code verification. Django validates the token against the configured Firebase project and checks the verified phone against the account.
6. If the role policy requires email as a second step, Django sends a separate email code. The user enters it in a separate field.
7. Django creates the authenticated portal session only after the required checks pass, then routes the user to the dashboard for their role.

The SMS box and the email box verify different challenges. A success notice or typed digits alone do not prove SMS verification; the server checks the signed Firebase result. Firebase controls its own carrier, region, quota, and abuse rules. The portal cannot force delivery.

### Accounts and access requests

Student and Teacher registrations create pending access requests. An Administrator reviews and approves them. Request status checks whether an access request exists; it is a separate action from logging into an approved account. Password recovery uses a purpose-specific email challenge and its own request limits.

### MFA controls

Administrators can open **Administrator Dashboard → Security → MFA Settings** at `/administrator/security/mfa/`. Portal MFA policies are stored separately for Students, Teachers, and Administrators. The administrator must confirm a change. Enabling an unavailable provider is rejected. If both factors are required, the portal asks for SMS first and email second.

An authorized administrator can turn MFA off for a role. That removes the portal OTP step for that role on future sign-ins and weakens that role's protection. Changing a role policy invalidates pending portal OTP sign-ins for that role. Existing sessions remain active. Password-reset codes are unaffected. Keycloak TOTP is a separate, global control that works only when the Keycloak Admin API and a manageable active flow are configured.

## Roles and school workflows

- **Student:** views permitted profile, course, enrollment, assignment, exam result, and attendance information.
- **Teacher:** works with assigned courses, class rosters, attendance, and related school records.
- **Administrator:** reviews access requests, manages portal accounts and school records, uses lockout controls, changes MFA policy, and reviews security events.

Django checks the user's role and approval status on protected views. The UI is not the access control boundary; the server checks permissions when a request arrives.

## Database handoff

The application uses PostgreSQL in deployments and Django migrations to describe changes to the database. The migration files are under `accounts/migrations/` and `school/migrations/`. Django also creates its standard user-permission, session, and content-type tables.

`Database/ERD.svg` summarizes the application tables and relationships. `Database/DATABASE_HANDOFF.txt` explains how to create a local database, apply migrations, and handle backups. The USB contains no production database dump or real database password. Copying source files cannot transfer a Neon account or production records. A separate authorized Neon owner must grant account access or provide a protected database backup.

## Security controls in source

The application code includes server-side role and approval checks, CSRF protection, secure production cookie and HTTPS settings, password lockouts, OTP expiry and attempt limits, resend cooldowns, database-backed quota records, privacy-preserving HMAC quota identifiers, session handling, and audit events. OTP codes are hashed for storage. The Firebase phone result is verified on the server.

Documented source defaults include a five-minute OTP lifetime, a five-minute sign-in resend wait, a limit of three sends per account/channel in its configured window, a 30-minute send lock after that limit, and up to five code attempts. Password recovery also has an IP limit and a separate per-account email-send limit. Deployment settings can override some values. Firebase imposes additional provider-side controls and charges.

These controls lower risk; they do not make an application “unhackable.” A source scan and automated tests are not the same as a production penetration test. The current review did not send real SMS or email codes, log in to production, inspect the Neon database, or test the deployed Vercel service.

## Verification record

On 1 October 2026, the isolated local Django suite passed **145 tests** using SQLite in-memory settings and an in-memory email backend. Ruff passed. Django's system check reported no issues. `makemigrations --check --dry-run` reported no schema changes pending.

The Codex Security diff review examined all 13 changed security-relevant files and reported no new findings. The earlier source scan found two issues in preview database URL normalization and password-reset audit accuracy; this patch addresses both and includes regression coverage. The security review is source-level. It did not exercise production PostgreSQL locking under concurrency, Firebase delivery, SMTP, Keycloak, or live Vercel behavior.

The team previously reported that SMS OTP worked for them. That is team-reported live evidence; this review did not repeat a hosted login or request any code. A GitHub push may trigger Vercel only if the repository remains connected to the intended Vercel project. Confirm the latest deployment in Vercel before calling the hosted release complete.

## Local Windows setup

Use fictional demonstration data only. Do not run demo seed or cleanup commands against production or real school records.

Prerequisites: Python 3.12, PostgreSQL 17, pgAdmin 4, and a current browser.

1. Create a dedicated local PostgreSQL database and application role. Do not use the PostgreSQL superuser for the application.
2. Copy `.env.example` to a private `.env`. Set a new local Django secret and a local database URL. Configure external providers only if you intend to test them. Do not commit `.env` or copy production secrets into the demo.
3. In PowerShell, from the project root:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   .\.venv\Scripts\python.exe manage.py migrate
   .\.venv\Scripts\python.exe manage.py seed_demo
   .\.venv\Scripts\python.exe manage.py configure_demo_logins
   .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
   ```

4. Visit `http://127.0.0.1:8000/`. Student and Teacher request forms are at `/signup/student/` and `/signup/teacher/`; status is at `/signup/status/`.
5. Run local checks with isolated settings:

   ```powershell
   .\.venv\Scripts\python.exe manage.py test --settings=config.test_settings --noinput
   .\.venv\Scripts\ruff.exe check .
   .\.venv\Scripts\python.exe manage.py check --settings=config.test_settings
   .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.test_settings
   ```

The isolated test settings use a temporary SQLite database and in-memory email. They do not validate Firebase, a phone carrier, SMTP delivery, Keycloak, Neon, or production data.

## Configuration and access

`.env.example` lists the supported environment variable names. The main groups cover Django, database connection, login and lockout rules, email delivery, Firebase web configuration, and optional Keycloak. The example file contains no live passwords. Store actual production credentials in the provider's protected environment settings.

The local access workbook and portal credential file contain sensitive account material. Keep them with the authorized administrator and encrypt the USB. GitHub and Vercel ignore these files. Do not put database URLs, email app passwords, client secrets, OTP values, or user passwords in code, the PDF, the PowerPoint, or screenshots. Anyone who receives the USB may be able to read those two local files, so share the USB only with the person authorized to control the portal.

## Deployment and ownership

The project uses GitHub for source and CI, Vercel for the portal, Neon for PostgreSQL, Firebase for phone verification, and the configured email provider for email codes. A source folder is not a transfer of these cloud accounts. A new owner needs to be granted appropriate access in each service and must set environment variables in their own provider account.

Before an actual handover, the current owner should verify the latest GitHub workflow, Vercel deployment and domain, database migration state and backup, Firebase authorized domains and SMS policy, email delivery, Keycloak status if used, and recovery contacts. Keep the owner account protected by MFA. Rotate credentials if the USB has been exposed.

## Project story for a presentation

Schools need different people to see different information. AuthShield 360 connects a role-based school portal to a sign-in process that can ask for both phone and email verification. A student registration waits for administrator approval, a teacher works with assigned classes, and administrators manage the records and security settings. The team used Django for application rules, PostgreSQL for persistent records, Firebase for phone verification, and Vercel for web hosting. The source and checks live in GitHub. The design keeps responsibilities visible so a maintainer can explain what each service does and where cloud ownership still matters.

## Questions a jury may ask

**Why use Django?** It provides request routing, forms, authentication primitives, database models, migrations, and server-side permission checks in one Python web framework.

**Why PostgreSQL and Neon?** PostgreSQL stores relational school records with constraints and transactions. Neon provides a hosted PostgreSQL service. Django migrations make the schema reproducible without copying a live database file.

**Why Firebase for SMS?** Firebase Phone Authentication runs the phone verification flow, reCAPTCHA check, and SMS delivery. Django verifies Firebase's signed token before trusting the phone result.

**Why does email come after SMS?** The configured SRS flow is password, SMS OTP, then email OTP. The system checks each step separately before creating the application session.

**What does Keycloak do?** It can act as an OIDC identity provider and can require authenticator-app TOTP if the server and its Admin API are configured. It is not the service sending Firebase SMS.

**How do the role controls work?** An administrator saves a separate persisted policy for each role. Future sign-ins follow that policy. Disabling MFA removes portal OTP for the selected role, so this is a security-sensitive administrator action.

**Is it fully security certified?** No. The source and automated checks have been reviewed, but there was no live penetration test or complete production audit in this handoff.

**Is the database included?** Its schema and setup instructions are included as source migrations and database documentation. A live production data dump and provider credentials are not included.

## Future work

Use separate Neon branches and verified migration automation for production and preview. Add a repeatable browser test using Firebase fictional numbers, without sending real messages. Verify production MFA policies and Keycloak state from provider evidence. Record deployment identifiers, accessibility findings, backup restoration results, and response-time measurements. Add monitored provider delivery health and an incident recovery plan. Review SMS as a fallback channel against passkeys or authenticator-app MFA for future releases.

## Official references

- Django security: https://docs.djangoproject.com/en/5.2/topics/security/
- Django authentication: https://docs.djangoproject.com/en/5.2/topics/auth/
- Django database models and migrations: https://docs.djangoproject.com/en/5.2/topics/db/
- Firebase Phone Authentication for the web: https://firebase.google.com/docs/auth/web/phone-auth
- Neon database branching: https://neon.com/docs/get-started-with-neon/workflow-primer
- Vercel Functions: https://vercel.com/docs/functions
- GitHub Actions: https://docs.github.com/en/actions
- Keycloak Server Administration Guide: https://www.keycloak.org/docs/latest/server_admin/
