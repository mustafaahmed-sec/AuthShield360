# Local restart, seed, and activity-feed evidence

**Date:** 2026-09-28
**Environment:** disposable `tmp/srs_evidence.sqlite3` SQLite database with isolated local settings. No hosted database or production account was accessed.

## Seed repeatability

Ran `manage.py seed_demo --settings=tmp.srs_settings` three consecutive times. Each run reported the same seeded totals:

- 486 Students
- 32 Teachers
- 3 Administrators
- 104 courses, 312 assignments, 1,944 enrollments, and 1,944 exam results

The repeated runs did not increase those counts.

## HTTP sign-in and process restart

Using a generated, fictional local Administrator account, signed in through `/login/`, loaded `/dashboard/`, and opened `/administrator/management/`. The new successful-login event was visible in the administrator activity feed within an upper bound of **139.74 ms**, measured from before the login POST through the rendered feed response.

Stopped and restarted the Django development server while keeping the browser session cookie in memory. After restart:

- `/dashboard/` returned HTTP 200 with the same signed-in browser session.
- The successful-login event remained visible in the administrator feed.
- Database totals remained 487 Students, 33 Teachers, 4 Administrators, 104 courses, 312 assignments, 1,944 enrollments, and 1,944 exam results. The extra three accounts are temporary restart-check users; the official seeded totals above exclude them.
- Audit events remained in SQLite.

This demonstrates local database and session persistence across an application-process restart. It does not prove Neon/Vercel persistence, multi-instance session behavior, or provider delivery. A separate automated logout test verifies that a logged-out session cannot be reused.

## Re-run

The run used a temporary helper and settings module under `tmp/`; these are local evidence helpers and must not be deployed. The human-safe reset and seed procedure is documented in [`../RESTART_AND_RESET.md`](../RESTART_AND_RESET.md).
