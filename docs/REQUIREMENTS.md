# AuthShield 360 SRS closeout

**Source:** `AuthShield 360-Ethical Cyber Horizons_SRS.pdf`, version 1.0, 21 pages.
**Review date:** 2026-09-28.
**Scope:** Local source, automated checks, selected Vercel configuration, Firebase Console settings, public Keycloak OIDC discovery, the portal Neon schema, and the production login page. The portal was redeployed after migration; no portal account or school-record data was changed, and no live SMS was sent.

## Requirement status

| SRS requirement | Status | Verification and remaining proof |
| --- | --- | --- |
| Fictional school portal, sample records, assignments, results, attendance, and admin functions | Implemented locally | Role-specific views and repeatable fictional seed are covered by automated tests. Local seed/restart counts are in [`evidence/restart-persistence-local.md`](evidence/restart-persistence-local.md). Confirm the intended demo database before using seed/reset commands. |
| Student, Teacher, and Administrator accounts and role boundaries | Implemented locally | Server-side role checks, approval gates, teacher roster scope, and admin-only management have automated coverage. Hosted walkthrough remains pending. |
| Password-only baseline and secure password handling | Implemented locally as a selectable lab stage | Django's password hasher is used. Automated tests cover the baseline flow; the SRS-required test-mode comparisons are in [`evidence/authentication-performance-local.md`](evidence/authentication-performance-local.md). These are local test-client timings, not browser or hosted timings. |
| Password + OTP and valid, invalid, expired, replayed, and missing-factor cases | Implemented in code | Email challenges are stored hashed and are single use. Firebase phone tokens are verified server-side. Automated checks pass using local/mock providers; live SMS delivery is not proven. |
| SMS OTP followed by email step-up | Implemented behind configuration | `AUTHSHIELD_EMAIL_STEP_UP=true` requires SMS and a second email code. Both factors passed isolated tests with provider behavior simulated. Firebase reCAPTCHA and carrier delivery have not been completed live. |
| Failed-login protection and account lockout | Implemented locally | Password failure lockout/escalation and cross-session SMS send/guess limits have automated coverage. Migrations `0009` and `0010` must be applied before deploying the current schema-dependent code. |
| Session security, logout, and old-session reuse | Implemented locally | Logout, session expiry, and stale-cookie checks pass in the test suite. Hosted restart and session behavior still need evidence. |
| Authentication logging and monitoring | Implemented locally | Authentication and admin actions write structured events; the admin activity view reads persisted events. Local event visibility was under 140 ms, but the SRS target still needs measurement on the hosted demo. |
| Controlled ethical testing with browser DevTools plus ZAP or Burp | Pending | Automated authorization tests pass. No ZAP/Burp report has been produced. Docker Desktop's engine returned an API error and Java/ZAP is not installed, so the tool assessment has not run. Keep all such testing on localhost with fictional accounts. |
| Mandatory Identity Security Test Matrix | Prepared with local and pending evidence separated | [`IDENTITY_SECURITY_TEST_MATRIX.md`](IDENTITY_SECURITY_TEST_MATRIX.md) uses the SRS-required fields: Test ID, User/Role, Test Action, Expected Result, Actual Result, Pass/Fail Status, and Evidence. |
| Configuration reset and repeatable test data | Implemented and locally verified | The `seed_demo` command is repeatable in a disposable database. [`RESTART_AND_RESET.md`](RESTART_AND_RESET.md) warns against running reset on hosted or non-disposable data. |
| Compatibility, usability, accessibility, and maintainability | Partly implemented; manual review remains | Responsive authentication screens and keyboard-friendly controls are present. A browser/device walkthrough and accessibility inspection are still needed; no broad accessibility certification is claimed. |
| Final report, presentation, MP4, and submission ZIP | Not complete | Existing local status/evidence files are not the final submission. The final MP4 must be recorded from the real approved demo; live/manual evidence must not be fabricated. |

## Live service state checked

- **Firebase:** Phone provider is enabled for project `authshield360-8b987`; `authshield360.vercel.app` is authorized. SMS region policy currently allows Pakistan and Colombia. The Firebase web key's reCAPTCHA-parameters endpoint returned HTTP 200. Matching web configuration is saved in the portal Vercel Production environment, but a portal deployment has not yet consumed those values. No CAPTCHA or paid/live SMS test was performed.
- **Keycloak:** `https://authshield360-keycloak.vercel.app` responds with successful OIDC discovery. The `authshield` realm and `authshield-portal` client exist. The portal has the Keycloak client configuration in Vercel but `AUTHSHIELD_KEYCLOAK_ENABLED=false`; Keycloak SMTP, registration, verification email, and a real portal callback sign-in remain unverified. The current Vercel container configuration is an evaluation/demo setup, not a resilient identity cluster.
- **Neon:** The current Neon account exposes `authshield360-db` (project ID `sparkling-mountain-48984319`) with `main` as its default branch. The previously supplied ID `patient-fog-02499412` could not be accessed under the signed-in account. The separate `authshield360-keycloak-db` belongs to Keycloak and did not receive Django portal migrations. Migrations `0008`–`0010` passed on a temporary schema-only branch and were then applied to the portal `main` branch; only schema changed.
- **Deployment:** Production deployment `dpl_3yFGy4jyx47LD4MQzpZNi1RSoaKf` is Ready and aliased to `https://authshield360.vercel.app`. The public `/login/` returned HTTP 200, rendered the sign-in form and SMS + email verification notice, and did not show a Keycloak button. This verifies page delivery/configured presentation, not an authenticated sign-in or live OTP.

## Project decisions and submission notes

- Use only fictional or participant-owned accounts and records for evidence. Never put real school data, passwords, OTPs, Firebase secrets, SMTP credentials, or database URLs in reports or screenshots.
- Firebase Phone Auth is the configured SMS provider; Gmail SMTP is the email OTP channel. A real delivery check requires the participant to complete Firebase reCAPTCHA and enter the code on their own controlled test device.
- Keycloak is an optional identity-provider integration, not a mandatory SRS platform. Django remains responsible for school approval and role authorization; Firebase remains the portal's phone-verification provider.
- Teachers can work only within assigned school records. They do not get student-password reset access.
- The supplied SRS page 18 says not to copy project content or configuration from GPT/AI tools. The user previously reported separate teacher guidance allowing AI assistance when the implementation is understood. Keep that clarification in writing, follow the teacher's final rule, and do not misrepresent tool-assisted work as solely student-authored.

## Remaining work before claiming the full SRS is complete

1. Run the live Firebase SMS flow on a participant-owned test account after the participant completes CAPTCHA and code entry; record the provider result without exposing the OTP or phone number.
2. Complete the authorized local DevTools plus ZAP or Burp assessment, review each finding, and attach the tool report.
3. Measure audit-feed visibility, restart persistence, and three-run login times against the intended demo environment; local measurements alone do not satisfy hosted evidence.
4. Record the human-visible walkthrough and assemble the final report, presentation, and submission ZIP from the verified local and live results.
