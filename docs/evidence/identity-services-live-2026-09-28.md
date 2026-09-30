# Identity service setup evidence — 28 September 2026

This note records configuration checks completed against Firebase and Vercel. It contains no API keys, passwords, OTPs, or database URLs.

## Firebase Phone Authentication

- Firebase project: `authshield360-8b987`.
- Phone sign-in provider is enabled.
- `authshield360.vercel.app` is present in Firebase Authentication's authorized domains.
- SMS region policy is set to **Allow** for Pakistan and Colombia. Other countries are not allowed by the current policy.
- The project's current web API key returned HTTP 200 from Firebase's `recaptchaParams` endpoint.
- Matching Firebase web configuration was saved to the portal Vercel project's Production environment variables. A portal redeploy is still required for the running deployment to receive those values.
- No live SMS was sent, and no CAPTCHA or end-user OTP flow was completed. SMS delivery, carrier delivery, and a successful sign-in therefore remain unverified.

## Keycloak service

- The separate `authshield360-keycloak` Vercel Production project is Ready at `https://authshield360-keycloak.vercel.app`.
- Keycloak 26.7.4 starts with the PostgreSQL-backed stateless feature. Production OIDC discovery returned HTTP 200 for both `master` and the `authshield` realm.
- The `authshield` realm and confidential `authshield-portal` OIDC client exist. The portal callback and origin are configured for `https://authshield360.vercel.app`.
- Keycloak bootstrap credentials and the portal client secret are stored under `%LOCALAPPDATA%\AuthShield360\`; they are not in the repository.
- The portal's Production environment now has the Keycloak issuer, realm, client ID, and client secret, while `AUTHSHIELD_KEYCLOAK_ENABLED` is explicitly `false`. The portal must remain on its current login flow until its database migration and callback flow are verified.
- Realm registration is disabled, email verification/SMTP is not configured, and no real-user or end-to-end portal login was performed.
- Vercel container logs showed separate instances and unavailable cluster communication. The current container uses local cache mode for this evaluation deployment; this does not establish a resilient multi-instance Keycloak production service.

## Portal database migration

- The Neon account lists the portal database project as `authshield360-db`, project ID `sparkling-mountain-48984319`, with `main` as its default branch. The separate `authshield360-keycloak-db` project is reserved for Keycloak.
- The earlier supplied project ID `patient-fog-02499412` did not resolve under the authenticated Neon account. No credentials were copied into this evidence file.
- Created the temporary schema-only branch `srs-migration-check-20260928`, which expires on 2026-09-30. It contained no copied user rows. The existing schema was checked, prior migration history was marked only in this disposable branch, and migrations `0008_user_keycloak_subject`, `0009_smsotpdeliverylimit`, and `0010_smsotpdeliverylimit_verification_attempts` were applied successfully there.
- Read-only inspection of portal `main` showed migrations `0001`–`0007` already applied and `0008`–`0010` pending. The same three additive migrations were then applied successfully to portal `main`; post-migration status confirmed all three applied. No account or school-record data was changed by those schema migrations.
- Production deployment `dpl_3yFGy4jyx47LD4MQzpZNi1RSoaKf` is Ready and aliased to `https://authshield360.vercel.app` after the database migration and Firebase environment-variable update.
- The public `/login/` route returned HTTP 200 with title `Sign in | AuthShield 360`; the deployed page displayed the SMS + email verification notice and no Keycloak button. This did not send SMS or complete an authenticated session. Read-only `showmigrations` confirmed the three new migrations applied and `migrate --plan` reported no remaining operations.

## Remaining live verification

1. Run an authorized real-device SMS test with the participant completing reCAPTCHA and entering the OTP.
2. Configure Keycloak SMTP and public registration/email verification only if the portal will use Keycloak for student and teacher registration.
3. Enable Keycloak only after a complete real login, callback, email verification, OTP, logout, and administrator-account check passes.
4. Repeat audit-feed timing, restart/persistence, and login-time measurements against the intended hosted demo, then record the final presentation and video.

## Read-only closeout update — 29 September 2026

- The production portal schema is confirmed migrated through `0011_publicrequestthrottle`; the temporary schema-validation branch has been removed. Migration `0011` adds the public request throttling model. No application account or school-record rows were changed during the migration work.
- Production GET requests to `/`, `/login/`, `/signup/student/`, `/signup/teacher/`, and `/signup/status/` each returned HTTP 200. This check verifies that these routes render; it did not authenticate a user or send a message.
- The full local Django suite passed 110 tests in 20.54 seconds. Ruff and `makemigrations --check --dry-run` passed. GitHub Actions passed for commit `955ff9d`, and Vercel reported the deployment Ready.
- The production page check does not prove Firebase CAPTCHA completion, SMS or email delivery, completed MFA, hosted audit-feed timing, or restart persistence.

## Release update — 30 September 2026

- Added administrator-managed per-role portal MFA policies and a separate Keycloak authenticator-app TOTP control. A changed role policy invalidates pending portal OTP sign-in attempts; active sessions and password-reset challenges are unaffected.
- Added migration `0012_keycloakmfapolicy_rolemfapolicy` for policy storage. Apply and verify it on the production portal database as part of the deployment before marking the release complete.
- The local suite passed 119 tests, Ruff passed, and Django reported no migration drift. Live Firebase SMS and hosted authenticated sign-in remain unverified.
