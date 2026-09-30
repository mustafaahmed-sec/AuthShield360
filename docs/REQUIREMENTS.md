# AuthShield 360 SRS closeout

**Source:** AuthShield 360-Ethical Cyber Horizons SRS, version 1.0 (21 pages).
**Review date:** 2026-09-30.
**Scope:** Local source and tests, tracked setup and evidence documents, selected Firebase/Keycloak/Vercel settings, Neon schema status, and read-only public route checks. No production account or school-record data was changed and no live SMS was sent.

## Requirement status

| SRS requirement | Status | Evidence and remaining proof |
| --- | --- | --- |
| Fictional school portal, sample records, assignments, results, attendance, and admin functions | Implemented locally | Role dashboards, school data, repeatable fictional seed, attendance, and management actions have automated coverage. Seed and restart totals are documented in [restart evidence](evidence/restart-persistence-local.md). |
| Student, Teacher, and Administrator accounts and role boundaries | Implemented locally | Approval gates, server-side role access, teacher roster scope, and admin-only management are covered by automated tests. Hosted authenticated walkthrough remains pending. |
| Password-only baseline and secure password handling | Implemented locally as a comparison stage | Django password hashing and the baseline flow have test coverage. The preliminary browser/local baseline is documented in [baseline evidence](evidence/password-only-baseline.md); local benchmark values are in [performance evidence](evidence/authentication-performance-local.md). |
| Password plus OTP, including invalid, expired, replayed, and missing-factor cases | Implemented in code; provider behavior simulated in automated checks | Email challenges are stored hashed and single-use. Firebase phone verification tokens are checked server-side. Role policy changes invalidate pending portal sign-ins. Current tests use local/mock providers; live delivery and user sign-in are not proven. |
| SMS OTP followed by email step-up | Implemented behind configuration | Both stages pass isolated automated tests with simulated providers. Production login-page delivery currently shows the SMS and email step; a real Firebase CAPTCHA, SMS delivery, email receipt, and completed sign-in remain unverified. |
| Failed-login protection and account lockout | Implemented locally | Account lockout, escalation/reset behavior, cross-session SMS send and guess limits, public signup/IP throttles, and blocked-audit caps have automated coverage. |
| Sessions, logout, and old-session reuse | Implemented locally | Logout, expiry, and stale-cookie checks pass automated tests; local process-restart persistence is documented. Hosted restart/session behavior remains unverified. |
| Authentication logging and monitoring | Implemented locally | Structured authentication and administrator events are persisted and shown in the admin activity view. Local visibility was measured under 140 ms; the hosted five-second target still needs measurement. |
| Identity Security Test Matrix | Prepared and refreshed | [The matrix](IDENTITY_SECURITY_TEST_MATRIX.md) separates automated results from live/manual results and uses the SRS-required fields. |
| Configuration reset and repeatable sample data | Implemented and locally verified | `seed_demo` is repeatable in a disposable database. [Reset instructions](RESTART_AND_RESET.md) warn against resetting a hosted or non-disposable database. |
| Compatibility, usability, accessibility, and maintainability | Partly implemented | Responsive authentication views and keyboard-friendly controls exist. A documented browser/device and accessibility walkthrough remains pending; no accessibility certification is claimed. |
| Report and presentation | Prepared from evidence | The local closeout report and portfolio description summarize implemented behavior and evidence while clearly marking remaining live work. They do not replace a team-recorded demo. |
| Mandatory MP4 demonstration and consolidated ZIP | Partly complete | A source package ZIP is prepared. The SRS-required human-recorded MP4 has not been recorded; it must show the real approved demo and must not be simulated or fabricated. |

## Live service checks

- **Firebase:** Phone provider and deployed domain authorization were previously checked in Firebase Console. The deployed sign-in page currently renders the SMS/email verification step. No reCAPTCHA, real SMS, email delivery, or completed sign-in was performed in this review.
- **Keycloak:** The separate service's OIDC discovery, realm, and client were previously checked. Portal Keycloak integration remains disabled while SMTP, registration, and real callback sign-in are unverified. It is optional to this SRS implementation.
- **Neon:** Portal schema migrations through `0011_publicrequestthrottle` were applied on the production portal database before this MFA dashboard release. Migration `0012_keycloakmfapolicy_rolemfapolicy` adds policy tables and must be applied before or during deployment. These are schema changes only; no account or school-record rows are intended to change. Keycloak uses its separate database.
- **Vercel:** The production home, `/login/`, `/signup/student/`, `/signup/teacher/`, and `/signup/status/` routes returned HTTP 200 on 2026-09-29. A successful GET proves route delivery only; authenticated access, provider delivery, and persistent hosted operations were not exercised.
- **Automation:** The full local Django test suite passed 119 tests in 21.97 seconds on 2026-09-30. Ruff and Django migration-drift checks passed. These local checks do not replace the post-deployment route and migration checks for this release.

## Current limits before claiming the full SRS complete

1. Complete one participant-owned live Firebase SMS and email step-up flow, without recording or sharing the actual phone number or OTP.
2. Measure audit-feed visibility, restart persistence, and the three-run authentication timings against the intended hosted demo environment.
3. Record the required human-visible demonstration video and capture the SRS evidence from that real session.
4. Conduct the remaining manual browser, compatibility, and accessibility walkthrough and update the matrix with actual outcomes.

No live result is inferred from local mocks, a page load, a configured provider, or a deployment status. See [the complete test matrix](IDENTITY_SECURITY_TEST_MATRIX.md) and its linked evidence files for test-level detail.
