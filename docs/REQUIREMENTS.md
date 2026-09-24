# AuthShield 360 requirement map

Source: `D:\AuthShield 360-Ethical Cyber Horizons_SRS.pdf`, version 1.0, 21 pages.
Progress marks: `pending`, `in progress`, `done`. The last row is an optional enhancement, not part of the minimum build.

| Area | Status | Source / decision |
| --- | --- | --- |
| Fictional school portal with Student, Teacher, Administrator accounts and dummy records | Done | SRS 1.4, 1.6(i-ii); teacher says the team builds it |
| Password-only baseline with success/failure and login time | In progress | Local login works; comparison measurements remain. SRS 1.2 scenario 1, 1.6(iii) |
| Secure password storage through Django authentication | Done | SRS 1.6(iv) |
| OTP MFA with valid, invalid, expired and missing factor cases | Pending | SRS 1.2 scenario 2, 1.6(v-vi) |
| Mobile OTP followed by time-limited email OTP | Pending | SRS 1.2 scenario 3; teacher requires email OTP |
| Server-enforced role access | In progress | Admin/Teacher/Student scopes are enforced; tests cover approval, assigned-student boundaries, and Admin-only roster changes. Broader matrix testing remains. SRS 1.6(vii) |
| Failed-login protection and session validation | Pending | SRS 1.6(viii-ix) |
| Authentication logging and monitoring | Pending | SRS 1.6(x) |
| Authorized DevTools and ZAP or Burp testing | Pending | SRS 1.6(xi); Kali VM available |
| Identity Security Test Matrix and evidence | Pending | SRS 1.6(xii), 1.9 |
| Repeatable reset and controlled restart persistence | In progress | Reset command works; restart evidence remains. SRS 1.6(xiii), 1.7 |
| Three-run login-time averages and event visibility within five seconds | Pending | SRS 1.7 |
| Report, presentation, MP4 demo, ZIP and README | Pending | SRS 1.9 |
| Student and Teacher requests, Admin approval, teacher roster search, scoped record edits, admin-reviewed roster requests, activity history | Optional enhancement implemented | Consistent with the fictional three-role portal and server-side role controls in SRS 1.4 and 1.6(ii, vii); OTP and AI remain excluded from this phase |
| Automated tests for approval, scope, and admin-reviewed roster changes | Optional enhancement implemented | Run all tests with `python manage.py test --settings=config.test_settings`; tests use a temporary in-memory SQLite database |

## Clarifications and assumptions

- The SRS describes a provided or preconfigured portal and says not to copy project content or configuration from AI tools. The teacher later instructed the team to build the portal and permits AI assistance when the student understands the work. We follow the teacher's clarification and document the contribution clearly.
- Email step-up is conditional in SRS 1.4 and 1.6(xii), but required by the teacher. It is therefore in the implementation plan.
- Mobile delivery is undecided between SMS and WhatsApp. A local test channel will be used first; the production provider remains pending.
- Public forms allow separate Student and Teacher access requests; the account is inactive until an Administrator approves it. Administrator accounts remain administrator-provisioned only.
- Applicants can check their own request status after authenticating with their email and password. No external email notification or OTP is implemented in this phase.
- Teachers can search and filter only students enrolled in their own classes and can edit a bounded set of school-record fields. Roster additions/removals remain requests that only an Administrator can approve.
- Initial role matrix: Students read their own records, assignments, and results; Teachers read and manage only assigned classes and their related work; Administrators manage accounts, roles, and school records. This is a least-privilege assumption until the teacher specifies finer rules.
- The online presentation format is unconfirmed. Local demonstration and the mandatory MP4 are planned; deployment needs a separate decision.
- The user subsequently requested a GitHub repository and Vercel deployment before OTP is built, and selected a protected demo link. The deployment uses fictional data, a separate hosted database, and Vercel Authentication. This changes the earlier local-only schedule, but does not remove the OTP requirement.

## Requirement classes

- **Required:** the portal, three role accounts, password baseline, OTP MFA, authorization, failed-login protection, logging, testing, matrix, reset, measurements, and submission evidence listed above.
- **Conditional in the SRS:** email step-up and account recovery where the selected platform supports them. The teacher has made email OTP required for this project; account recovery remains conditional.
- **Optional:** the professional enhancement backlog in the kickoff brief, after required work is reliable.
- **Awaiting a teacher decision:** SMS versus WhatsApp for mobile OTP delivery, and whether the remote jury needs a live URL or accepts a screen-shared local demo.
