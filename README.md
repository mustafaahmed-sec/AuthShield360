# AuthShield 360

A local fictional school portal for the Aptech TechWiz 7 identity-security demonstration. The current build has PostgreSQL-backed accounts and school records, public Student sign-up, a controlled local password-only login, role dashboards, Teacher record entry, and administrator management. Mobile and email OTP are the next authentication stages.

## What each tool does

- **Django** runs the web application and provides the account, form, and administration framework.
- **PostgreSQL** stores accounts and fictional school data persistently.
- **pgAdmin** is a developer tool for creating and inspecting the PostgreSQL database.
- **Django Admin** is the application's restricted interface for managing its accounts and records.

## Prerequisites

- Python 3.14 (supported by Django 5.2.8 and later)
- PostgreSQL 17 with pgAdmin 4
- A modern browser

## Local setup on Windows

1. Create a local PostgreSQL login role named `authshield_app` with a password and permission to log in. Create database `authshield360` owned by that role. Do this in pgAdmin as the PostgreSQL administrator. The application must use this dedicated role rather than the `postgres` superuser.
2. Copy `.env.example` to `.env`. Replace `DJANGO_SECRET_KEY` with a random value and put the role password after `DB_PASSWORD=`. Set `AUTHSHIELD_BASELINE_LOGIN=true` only for the local comparison stage and choose unique random values of at least 16 characters for the three `DEMO_*_PASSWORD` entries. The current project setup already generated these values in its ignored `.env`; keep them private. Do not commit or share `.env`.
3. From this folder, run the commands below in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py configure_demo_logins
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

4. Open `http://127.0.0.1:8000/` for the portal, `http://127.0.0.1:8000/signup/` for Student registration, and `http://127.0.0.1:8000/admin/` for the administrator interface.

The seed command creates a balanced fictional roster of 486 students, 32 teachers, and 3 administrators for the 2026–27 school year. Student counts are distributed 37–38 per grade from Kindergarten through Grade 12; ages follow the grade with a small, realistic variation. Every student is enrolled in four grade-appropriate course sections and has a term assignment and exam result in each, so the Teacher dashboard displays a complete class roster and academic records. The 485 generated student names are all unique: about three quarters use familiar US English-language naming styles, with the rest drawn from several cultural naming traditions common in US schools. Names are fictional and do not represent or record students' actual religion or ethnicity. The three administrator display names are Sara Miller, Grace Thompson, and Amina Qureshi. All generated users receive unusable passwords. The three primary demo login emails remain `ali.student@example.test`, `mina.teacher@example.test`, and `sara.admin@example.test`; their passwords remain in the ignored local `.env` file under `DEMO_STUDENT_PASSWORD`, `DEMO_TEACHER_PASSWORD`, and `DEMO_ADMIN_PASSWORD`. The two additional Administrator accounts are provisioned without passwords until the primary Admin explicitly assigns credentials. Never put passwords in screenshots, reports, or GitHub. You can set a new password interactively with `manage.py changepassword <email>`.

## Repeatable demo reset

`manage.py seed_demo` can be run again without duplicating the named records. It refuses to delete or demote accounts if a role already exceeds its target. `manage.py seed_demo --reset` deletes only generated `demo.*` accounts and `D26-*` course records, keeps the three primary demo accounts and their passwords, then recreates the roster. The existing `SCI-101` course remains the Grade 10 A science section. Run `manage.py configure_demo_logins` afterward only if the primary demo passwords need to be restored from `.env`.

## Current architecture

The browser calls Django. Django reads and writes PostgreSQL through its models. The `accounts` app defines a custom email-based User with Student, Teacher, and Administrator roles. Public sign-up can create Student accounts only. The `school` app defines student records, courses, enrollments, assignments, and exam results. Student dashboards query only the signed-in Student's records. Teacher dashboards query assigned courses and their related records; Teacher forms can add assignments and results only within those courses. Administrator dashboard access requires an Administrator role and Django staff/superuser privileges; Django Admin provides authorized record management. The password-only login is enabled only when `DJANGO_DEBUG=true` and `AUTHSHIELD_BASELINE_LOGIN=true`; it must be replaced by MFA before deployment.

The request flow is: browser form → Django view → validated form → PostgreSQL model. Sign-up stores a Django password hash in the User row and assigns the Student role. Sign-in checks that hash and creates a Django session; it does not send the password to the dashboard. Each dashboard query uses the current session user to filter records. Teacher forms restrict the course choices and validate the submitted course again on the server. Sign-out ends the session using a POST request.

| Role | Read access | Write access |
| --- | --- | --- |
| Guest | Public landing and sign-up pages | Create a Student account |
| Student | Own school record, enrolled courses, assignments, results | None yet |
| Teacher | Own courses, their students, assignments, results | Create assignments and exam results for assigned courses |
| Administrator | Portal totals and Django Admin records | Manage accounts, roles, courses, and school data in Django Admin |

See [the requirement map](docs/REQUIREMENTS.md) for the full SRS checklist and teacher clarifications.

## File map

| File | Purpose |
| --- | --- |
| `config/settings.py` | Loads local secrets, registers apps, and connects Django to PostgreSQL. |
| `accounts/models.py`, `accounts/forms.py`, `accounts/views.py` | Define accounts, Student-only sign-up, and the controlled baseline login. |
| `accounts/admin.py` | Makes authorized account management available in Django Admin. |
| `accounts/management/commands/configure_demo_logins.py` | Prepares three fictional role logins from local `.env` values. |
| `school/models.py`, `school/forms.py`, `school/views.py` | Define school data, role dashboards, and Teacher forms. |
| `school/management/commands/seed_demo.py` | Creates the balanced fictional 486-student, 32-teacher, 3-administrator roster and linked classwork. |
| `school/data/demo_students.json` | Supplies 485 distinct fictional student names and gender values for the demo roster. |
| `templates/`, `static/css/site.css` | Render and style the portal pages. |
| `docs/REQUIREMENTS.md` | Tracks SRS obligations, teacher clarifications, and open decisions. |

## Next milestones

1. Mobile OTP and required email OTP with expiry, reuse prevention, and test delivery.
2. Failed-login protection, security event logging, comparison runs, and authorized browser/Kali checks.
3. Identity Security Test Matrix, evidence, report, presentation, MP4 video, and ZIP submission.

## Vercel deployment preparation

This repository is configured for a protected Vercel demo while OTP is being developed. Vercel detects `manage.py`, uses `config/wsgi.py`, and collects static files from `STATIC_ROOT`. The deployed site uses a hosted PostgreSQL database; the laptop's PostgreSQL server remains local. The hosted connection is supplied to Vercel as `DATABASE_URL`. Keep all deployment secrets in Vercel environment variables, never in GitHub or `.env.example`.

Use a new `DJANGO_SECRET_KEY` for Vercel, set `DJANGO_DEBUG=false`, and set `AUTHSHIELD_BASELINE_LOGIN=true` only for the temporary password comparison. Set `AUTHSHIELD_PROTECTED_DEMO=true` only after Vercel Authentication protects the deployment. The local `.env` remains ignored and is not uploaded. Hosted database migrations, fictional seed data, and new demo passwords must be prepared separately from the local database.

The protected demo is deployed at [authshield360.vercel.app](https://authshield360.vercel.app/) from the private `mustafaahmed-sec/AuthShield360` repository. Vercel Authentication protection is enabled for Vercel deployment URLs; viewers need access through the Vercel account/team. The app uses the hosted Neon PostgreSQL database through Vercel's `DATABASE_URL` environment variable.

This online build is for fictional data and controlled demonstration while mobile and email OTP are unfinished. Do not use real school credentials or records. Password-only sign-in is enabled only for this protected demo stage. Deployment secrets are stored in Vercel; the generated fictional demo-account passwords are kept in the ignored local file `.vercel-deploy-credentials.txt` and must never be committed or shared publicly.
