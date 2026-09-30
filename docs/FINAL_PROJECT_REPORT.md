# AuthShield 360 — SRS Implementation and Verification Report

**Prepared:** 30 September 2026
**Requirements source:** AuthShield 360 — Ethical Cyber Horizons SRS, version 1.0
**Application:** Fictional school portal for the Aptech TechWiz 7 demonstration

## 1. Problem definition

The project demonstrates how a school portal can provide separate Student, Teacher, and Administrator experiences while comparing a password-only baseline with stronger, multi-factor sign-in. The application uses fictional school records so account approval, coursework, attendance, role restrictions, and authentication behavior can be demonstrated without using real student records.

## 2. Application architecture

The browser submits requests to a Django application. Django validates forms, applies account approval and role checks, performs authentication and audit actions, and reads or writes portal data through its models. PostgreSQL is used for persistent application data; the production portal database is hosted by Neon. The browser and Django each participate in Firebase Phone Authentication: Firebase performs the browser reCAPTCHA/SMS challenge, and Django validates the resulting signed Firebase token before completing the portal sign-in. Django also supports an email one-time code through its configured email backend.

Keycloak is an optional OpenID Connect identity provider. The current portal keeps Keycloak sign-in disabled; Django continues to own school roles, request approval, and portal authorization. The administrator MFA page can manage an unconditional authenticator-app TOTP execution when the server-side Keycloak Admin API is configured. This TOTP setting is separate from Firebase SMS and email OTP.

### Authentication flows

**Password-only comparison:** the evaluator signs in with a test account while the controlled baseline setting is enabled. This mode is for comparison and must not be treated as the verified production MFA result.

**MFA sign-in:** the user submits an email and password. When OTP is required, the password alone does not open a role dashboard. The user completes an available email or Firebase phone verification step; when email step-up is configured, both the SMS and email challenge must pass. Django enforces account state and approval before granting the portal session. Test coverage simulates provider results; live delivery remains unverified.

**Access request:** a Student or Teacher submits a request and waits for an Administrator to review it. Request status is checked with the credentials used for that request. Approval and school-role authorization remain in Django even if an external identity provider is configured later.

## 3. Tools and platforms

| Component | Purpose |
| --- | --- |
| Django and Python | Portal application, forms, authentication, role checks, management commands, and tests |
| PostgreSQL / Neon | Persistent portal accounts and school records |
| Firebase Authentication | Phone verification and SMS OTP delivery |
| Gmail SMTP / Django email backend | Email OTP and account messages |
| Vercel | Portal web deployment and separate optional Keycloak service |
| Keycloak | Optional OIDC identity service; disabled in the current portal login flow |
| GitHub Actions, Ruff, Django tests | Automated quality checks |

Credentials, API secrets, database URLs, password values, and OTP values are intentionally excluded from this report and the source package. Configuration belongs in ignored local environment files or the hosting provider's secret settings.

## 4. User and role access

| Role | Main access | Boundaries verified in local tests |
| --- | --- | --- |
| Student | Own enrolled courses, exam results, assignments, attendance, and profile | Cannot open teacher or administrator resources or another student's records |
| Teacher | Assigned classes, student search, attendance, assignments, and results | Records are scoped to assigned courses; administrator routes remain denied |
| Administrator | Account requests, account management, audit activity, attendance review, and school administration | Protected administrator actions require an administrator account and are audit logged |

The Administrator dashboard also links to **MFA settings** at `/administrator/security/mfa/`. This page sets the portal email/SMS methods per role and exposes Keycloak TOTP as a separate control. Saving a changed role policy immediately invalidates its pending portal OTP sign-in attempts. Existing sessions and password-reset challenges are unaffected.

Both Student and Teacher access requests require administrator approval before sign-in is allowed.

## 5. Verification results

On 30 September 2026, the complete Django suite ran with `config.test_settings`: **119 tests passed in 21.97 seconds**. Ruff and Django migration drift checks passed. These results establish code-level evidence; they do not establish every hosted user flow.

### Authentication and MFA

Automated checks cover successful and rejected passwords, password-only access not bypassing a required OTP, valid and invalid OTP handling, expired and replayed challenges, missing-factor attempts, SMS/email step-up ordering, cross-session send/guess limits, and login lockout behavior. Firebase, email, and OIDC responses are simulated or mocked in these tests. No live SMS, reCAPTCHA completion, email receipt, or real OIDC callback sign-in is claimed.

The local performance suite completes 27 sign-in cycles across three roles and three authentication modes. These are Django test-client timings using in-memory SQLite and simulated providers, not browser or hosted measurements. The latest recorded timings and every run are retained in `docs/evidence/authentication-performance-local.md`; the first cold Student email-OTP run is deliberately retained rather than excluded.

### Baseline comparison

The preliminary local baseline recorded three successful sign-ins per role, rejected incorrect passwords, denied cross-role access, and confirmed logout invalidates the prior session. It also documents the baseline account/password mismatch and other test limitations. See `docs/evidence/password-only-baseline.md`. The benchmark values are not production latency claims.

### Failed-login protection, logging, and persistence

Automated tests cover password failure thresholds, lockout and escalation, successful-login reset behavior, SMS delivery limits, OTP guess limits, and role authorization. The administrator audit view is covered by local persistence/visibility tests. A disposable SQLite restart exercise retained the demo records, login session, and audit events; its measured feed response was below the SRS five-second target. Hosted audit timing and hosted restart persistence remain unmeasured.

### Hosted route check

Read-only requests on 29 September 2026 returned HTTP 200 for `/`, `/login/`, `/signup/student/`, `/signup/teacher/`, and `/signup/status/`. The login page displayed the configured SMS/email verification step. This confirms public route rendering only. No credentials were submitted, and no authentication or OTP delivery was attempted.

## 6. Identity Security Test Matrix

The project matrix at `docs/IDENTITY_SECURITY_TEST_MATRIX.md` records test ID, user/role, action, expected result, actual result, status, and evidence. It separates automated local checks from production configuration and manual checks. Its current status is:

- Automated application checks: 119 tests passed locally.
- Portal database schema: migration `0012_keycloakmfapolicy_rolemfapolicy` adds portal MFA configuration tables and must be applied in production for this release.
- Vercel page delivery: the five public routes listed above returned HTTP 200.
- Live Firebase SMS and email step-up: not run.
- Live Keycloak callback: not run; the portal login integration is disabled. Keycloak TOTP settings are available only when its management API and a safe active flow are configured.
- Hosted audit visibility, hosted restart persistence, and hosted performance: not run.
- Human-recorded demonstration video: not recorded.

The SRS calls for controlled security-tool evidence. This report makes no claim that a ZAP or Burp assessment was completed; that evidence is marked pending in the matrix. Automated authorization tests are not a substitute for a tool assessment.

## 7. Usability and compatibility

The project includes responsive sign-in, recovery, OTP, Student, Teacher, and Administrator screens. Authentication pages use explicit labels and status messages; controls can be operated from a keyboard. The SRS browser/device and accessibility walkthrough still needs to be completed and recorded. No broad accessibility certification is claimed.

## 8. Repeatable setup and test data

Use the root `README.md` for prerequisites, Windows local setup, environment configuration, migrations, demo seeding, and test commands. Use `docs/RESTART_AND_RESET.md` before reset or restart demonstrations. The repeatable fictional seed locally produced 486 Students, 32 Teachers, 3 Administrators, 104 courses, 312 assignments, 1,944 enrollments, and 1,944 exam results. Seed/reset commands are for a disposable demonstration database; do not run reset against hosted or non-disposable school data.

Run the local suite using:

```powershell
.\.venv\Scripts\python.exe manage.py test --settings=config.test_settings --noinput
.\.venv\Scripts\ruff.exe check accounts config school
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.test_settings
```

## 9. Conclusions and remaining work

The portal implements the core fictional school workflows, role separation, approval process, OTP code paths, lockout rules, audit events, and repeatable sample data. Current code-level checks and production route checks pass. The evidence does **not** support declaring the full SRS complete because live provider delivery, authenticated hosted flows, hosted timing/restart measurements, manual browser/accessibility review, the tool evidence listed by the SRS, and the mandatory human-recorded MP4 remain outstanding.

Before final submission, the team should complete a participant-owned SMS and email step-up demonstration, collect hosted timing and persistence observations, perform the approved browser/device walkthrough, complete and document any required security-tool work in the authorized local environment, then record the MP4 and refresh the evidence matrix. Never include real credentials, OTPs, database URLs, or private student data in the submission.

## 10. Source references

- AuthShield 360 — Ethical Cyber Horizons SRS, version 1.0, especially sections 1.2 and 1.6–1.9.
- `README.md` and `docs/IDENTITY_SECURITY_TEST_MATRIX.md`.
- `docs/evidence/password-only-baseline.md`.
- `docs/evidence/authentication-performance-local.md`.
- `docs/evidence/restart-persistence-local.md`.
- `docs/evidence/identity-services-live-2026-09-28.md`.
