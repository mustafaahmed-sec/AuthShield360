# AuthShield 360

A fictional school portal for the Aptech TechWiz 7 identity-security demonstration. It has PostgreSQL-backed accounts and school records, separate Student and Teacher access requests, administrator approval, a configurable password-plus-OTP sign-in flow, role dashboards, attendance, student progress and due-soon summaries, a teacher student search and grade filter, recorded school-record edits, and administrator-managed roster changes. Email OTP uses Gmail SMTP; mobile OTP is a separate Twilio Verify integration.

## What each tool does

- **Django** runs the web application and provides the account, form, and administration framework.
- **PostgreSQL** stores accounts and fictional school data persistently.
- **pgAdmin** is a developer tool for creating and inspecting the PostgreSQL database.
- **Django Admin** is the application's restricted interface for managing its accounts and records.

## Prerequisites

- Python 3.12 or newer (3.12 is the minimum version checked in CI; deployment currently uses 3.14)
- PostgreSQL 17 with pgAdmin 4
- A modern browser

## Local setup on Windows

1. Create a local PostgreSQL login role named `authshield_app` with a password and permission to log in. Create database `authshield360` owned by that role. Do this in pgAdmin as the PostgreSQL administrator. The application must use this dedicated role rather than the `postgres` superuser.
2. Copy `.env.example` to `.env`. Replace `DJANGO_SECRET_KEY` with a random value and put the role password after `DB_PASSWORD=`. Set `AUTHSHIELD_BASELINE_LOGIN=true` only for the local comparison stage and choose unique random values of 12–50 characters for the three `DEMO_*_PASSWORD` entries (at least 25 for the Administrator). Each password must include a lowercase letter, uppercase letter, number, and special character. The current project setup already generated these values in its ignored `.env`; keep them private. Do not commit or share `.env`.
3. From this folder, run the commands below in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py configure_demo_logins
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

4. Open `http://127.0.0.1:8000/` for the portal, `/signup/student/` for Student registration, and `/signup/teacher/` for a Teacher access request. New requests remain inactive until an Administrator approves them. Applicants can check their status at `/signup/status/` with the same email and password, then sign in after approval.
5. Run all repeatable tests with `python manage.py test --settings=config.test_settings`. The test settings use an isolated in-memory SQLite database and do not change the local PostgreSQL database. For linting and migration checks, install `requirements-dev.txt`, then run `python -m ruff check .` and `python manage.py makemigrations --check --dry-run --settings=config.test_settings`.

## Password-only login protection and audit trail

The password-only comparison stage uses configurable limits, shown in `.env.example`: five failed login or request-status password checks for an account within 15 minutes trigger an account lock of at least 30 minutes. A longer lockout can be configured; shorter settings are raised to the 30-minute minimum. A successful sign-in or administrator unlock clears the account's failure count. As a separate source-level throttle, 30 failures from one observed IP in 15 minutes pause new attempts from that IP for one minute. The IP limit is deliberately higher because multiple legitimate users can share a network address. Administrators can unlock selected accounts from Django Admin's account list; the lock timestamp is read-only there, so unlocking is audit-logged.

Authenticated sessions use a rolling 15-minute idle timeout. A POST to Sign out invalidates the session; replaying its old cookie must not restore access. The audit trail records event time, account email and role, action, authentication mode, factor, success or failure, the IP address seen by Django, a short SHA-256 session hint, and elapsed authentication time where measured. It never stores passwords, OTP values, or raw session cookies. The Admin portal shows recent events; Django Admin provides filters and a selected-event CSV export. Audit rows are read-only.

The IP field records `REMOTE_ADDR` as observed by Django and deliberately does not trust a caller-supplied forwarded header. On a deployment behind a reverse proxy this may identify the proxy rather than the visitor until a trusted proxy configuration is verified. Localhost tests record `127.0.0.1`. See [the safe local reset and restart procedure](docs/RESTART_AND_RESET.md) before demonstrating persistence; it does not reset or migrate the live Vercel database.

## Troubleshooting

- If Django cannot connect to PostgreSQL, confirm the PostgreSQL service is running and that `DB_HOST`, `DB_PORT`, `DB_NAME`, and `DB_USER` in the local `.env` match the database setup.
- If the portal reports missing database tables, run `python manage.py migrate` from the project folder.
- If fictional school records are missing, run `python manage.py seed_demo`. To rebuild the generated demo roster and refresh its assignment due dates, use `python manage.py seed_demo --reset`.
- To add any missing sample assignments without touching accounts or student records, run `python manage.py seed_demo --assignments-only`.
- The Student dashboard shows course averages only after results exist. “Due soon” includes assignments due today through 14 days from today; an empty list means no enrolled-course assignments fall in that window.

The seed command creates a balanced fictional roster of 486 students, 32 teachers, and 3 administrators for the 2026–27 school year. Student counts are distributed 37–38 per grade from Kindergarten through Grade 12; ages follow the grade with a small, realistic variation. Every student is enrolled in four grade-appropriate course sections and has exam results plus three term assignments per course, so the Teacher dashboard displays a complete class roster and academic records. Seeded assignments have staggered due dates one, three, and five weeks ahead; this gives the Student dashboard both near-term and later work. The 485 generated student names are all unique: about three quarters use familiar US English-language naming styles, with the rest drawn from several cultural naming traditions common in US schools. Names are fictional and do not represent or record students' actual religion or ethnicity. The three administrator display names are Sara Miller, Grace Thompson, and Amina Qureshi. All generated users receive unusable passwords. The three primary demo login emails remain `ali.student@example.test`, `mina.teacher@example.test`, and `sara.admin@example.test`; their passwords remain in the ignored local `.env` file under `DEMO_STUDENT_PASSWORD`, `DEMO_TEACHER_PASSWORD`, and `DEMO_ADMIN_PASSWORD`. The two additional Administrator accounts are provisioned without passwords until the primary Admin explicitly assigns credentials. Never put passwords in screenshots, reports, or GitHub. You can set a new password interactively with `manage.py changepassword <email>`.

## Repeatable demo reset

`manage.py seed_demo` can be run again without duplicating the reserved fictional roster. It counts only the 485 generated Student accounts and three primary demo logins, so real pending or approved signups do not affect the target. Normal reruns preserve administrator edits to existing courses, school records, assignments, scores, and enrollments. `manage.py seed_demo --reset` deletes generated `demo.*` accounts and rebuilds their records. It retains courses so historical roster requests remain valid, and restores seeded course assignments and school data. The three primary demo accounts and their passwords remain. The existing `SCI-101` course remains the Grade 10 A science section. Run `manage.py configure_demo_logins` afterward only if the primary demo passwords need to be restored from `.env`.

## Current architecture

The browser calls Django. Django reads and writes PostgreSQL through its models. The `accounts` app defines a custom email-based User with Student, Teacher, and Administrator roles. Public forms accept Student and Teacher access requests; both require administrator approval. The `school` app defines student records, courses, enrollments, assignments, exam results, and dated course attendance. Student dashboards show their enrolled courses, average exam percentage per course, assignments due in the next 14 days, their own attendance, and their own records. Teachers can mark attendance for enrolled students in assigned courses, and their dashboards query only assigned courses and related records. Teacher forms can add assignments and results only within those courses. Administrators can review and correct attendance in Django Admin. Administrator dashboard access requires an Administrator role and Django staff/superuser privileges; Django Admin provides authorized record management. Password-only login requires `AUTHSHIELD_BASELINE_LOGIN=true` plus either local `DJANGO_DEBUG=true` or `AUTHSHIELD_PROTECTED_DEMO=true` for the protected demonstration. MFA is the next authentication stage.

Administrators can publish announcements in Django Admin for everyone or for one role. Optional start and end dates control when an active announcement appears on Student, Teacher, and Administrator dashboards.

The request flow is: browser form → Django view → validated form → PostgreSQL model. Student and Teacher signup store Django password hashes and set the account to pending and inactive. Only an Administrator can approve or reject that request; approval activates the account, and approved students receive an initial fictional school record. Applicants can check the request status using their email and password. Rejected applicants may resubmit with the same role, email, and password, and administrators may reopen rejected requests in the portal. Sign-in checks the password hash and approval state before creating a Django session. Each dashboard query uses the current session user to filter records. Teachers can search their assigned students, filter by grade/course, and edit a restricted set of student school-record fields; those edits are logged. Teachers cannot create or remove roster enrollments: they send an add/removal request, and only an Administrator can approve it. Sign-out ends the session using a POST request.

| Role | Read access | Write access |
| --- | --- | --- |
| Guest | Public landing, separate Student/Teacher request forms, own request-status lookup | Submit a pending Student or Teacher request; no Administrator role is offered publicly |
| Student | Own school record, enrolled courses, assignments, results | None yet |
| Teacher | Own courses, assigned students and their related records | Create assignments and results for assigned courses; edit allowed student-record fields; request (but cannot directly apply) roster enrollment changes |
| Administrator | Portal totals, requests, account data, and activity records | Approve/reject requests; activate/deactivate/delete Student and Teacher accounts; approve/reject roster changes; manage courses and academic data |

See [the requirement map](docs/REQUIREMENTS.md) for the full SRS checklist and teacher clarifications.

## File map

| File | Purpose |
| --- | --- |
| `config/settings.py` | Loads local secrets, registers apps, and connects Django to PostgreSQL. |
| `accounts/models.py`, `accounts/forms.py`, `accounts/views.py` | Define accounts, Student/Teacher access requests and status lookup, and controlled baseline login. |
| `accounts/admin.py` | Makes authorized account management available in Django Admin. |
| `accounts/management/commands/configure_demo_logins.py` | Prepares three fictional role logins from local `.env` values. |
| `school/models.py`, `school/forms.py`, `school/views.py` | Define school data and shared role dashboards. |
| `school/admin_views.py`, `school/teacher_views.py`, `school/access.py` | Keep administrator and teacher workflows separate and enforce shared portal role checks. |
| `accounts/tests.py`, `school/tests.py`, `school/test_seed_demo.py`, `config/tests.py`, `config/test_settings.py` | Automated coverage for login, requests, roles, roster changes, seed reruns, and deployment redirects on isolated SQLite. |
| `school/management/commands/seed_demo.py` | Creates the balanced fictional 486-student, 32-teacher, 3-administrator roster and linked classwork. |
| `school/data/demo_students.json` | Supplies 485 distinct fictional student names and gender values for the demo roster. |
| `templates/`, `static/css/site.css` | Render and style the portal pages. |
| `docs/REQUIREMENTS.md` | Tracks SRS obligations, teacher clarifications, and open decisions. |
| `.github/workflows/checks.yml`, `requirements-dev.txt`, `ruff.toml` | Run all tests, check migrations, and lint Python on pushes and pull requests. |

The fictional school displays dates in the `America/New_York` time zone. Change `TIME_ZONE` if the demonstrated school is assigned elsewhere. Application audit events are also written to server logs without credentials.

## Next milestones

1. Record the required password-only comparison runs and complete authorized browser/Kali checks.
2. Configure Gmail SMTP for free email OTP, then add a mobile OTP provider if the team enables the WhatsApp/SMS stage.
3. Complete the Identity Security Test Matrix, evidence, report, presentation, MP4 demo, and ZIP submission.

## OTP sign-in configuration

The login supports email OTP through Gmail SMTP and mobile OTP through Twilio Verify. Gmail email codes are generated by the application, stored as a one-time hash in the server-side session, and expire after `AUTHSHIELD_EMAIL_OTP_TTL_SECONDS` (60 seconds by default). The branded HTML email greets the account holder by name, displays the code clearly, and includes a plain-text version for email clients that do not display HTML. Email users can request a replacement code after 30 seconds. Other OTP channels keep the separate `AUTHSHIELD_OTP_TTL_SECONDS` (600 seconds by default). The portal limits code attempts and resends. `AUTHSHIELD_EMAIL_STEP_UP=false` (the default) uses one selected channel; Email is selected by default, so the email-only demo can use Gmail without a paid mobile provider. Set `AUTHSHIELD_EMAIL_STEP_UP=true` to require a mobile WhatsApp code followed by a second Gmail email code. Set `AUTHSHIELD_OTP_ENABLED=true` only after configuring the provider credentials needed for the chosen flow.

For free low-volume email testing, enable 2-Step Verification on the project Gmail account, create a Google App Password, then store `AUTHSHIELD_GMAIL_ADDRESS` and `AUTHSHIELD_GMAIL_APP_PASSWORD` as server-side environment variables in Vercel or the ignored local `.env`. Do not use the account's regular password, commit the App Password, or share it in chat. Gmail SMTP uses `smtp.gmail.com` on port `587` with TLS. For the WhatsApp-then-email flow, also configure Twilio Verify with a WhatsApp Business sender and set `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET`, and `TWILIO_VERIFY_SERVICE_SID`; mobile-provider usage may have charges. Mobile delivery is kept behind a separate provider adapter so SMS can be added later; the portal does not currently offer SMS sign-in. Keep phone numbers in international E.164 format. The fictional `example.test` addresses and generated phone numbers cannot receive real codes; use contact details controlled by the project team for delivery tests. Never expose provider credentials in frontend code or commit them.

## Vercel deployment preparation

This repository is configured for a protected Vercel demo while OTP is being developed. Vercel detects `manage.py`, uses `config/wsgi.py`, and collects static files from `STATIC_ROOT`. The deployed site uses a hosted PostgreSQL database; the laptop's PostgreSQL server remains local. The hosted connection is supplied to Vercel as `DATABASE_URL`. Keep all deployment secrets in Vercel environment variables, never in GitHub or `.env.example`.

Use a new `DJANGO_SECRET_KEY` for Vercel, set `DJANGO_DEBUG=false`, and set `AUTHSHIELD_BASELINE_LOGIN=true` only for the temporary password comparison. Set `AUTHSHIELD_PROTECTED_DEMO=true` only after Vercel Authentication protects the deployment. The local `.env` remains ignored and is not uploaded. Hosted database migrations, fictional seed data, and new demo passwords must be prepared separately from the local database.

The demo is deployed from the public `mustafaahmed-sec/AuthShield360` repository. The public [authshield360.vercel.app](https://authshield360.vercel.app/) alias redirects to the current protected deployment URL when `AUTHSHIELD_PROTECTED_DEMO=true`; viewers need access through the Vercel account/team. If the deployment URL is unavailable, the alias fails closed. The app uses the hosted Neon PostgreSQL database through Vercel's `DATABASE_URL` environment variable.

This online build is for fictional school data and controlled demonstration. Do not use real school credentials or records. Password-only sign-in remains the configured mode until OTP settings are added and `AUTHSHIELD_OTP_ENABLED` is enabled. Deployment secrets are stored in Vercel; the generated fictional demo-account passwords are kept in the ignored local file `.vercel-deploy-credentials.txt` and must never be committed or shared publicly.
