# SRS authentication performance: local isolated run

**Date:** 2026-09-29
**Command:** `.venv\Scripts\python.exe manage.py test --settings=config.test_settings --verbosity=1` (includes `accounts.test_performance`)
**Test result:** 110 tests passed in 20.54 seconds on 2026-09-29. The three benchmark scenarios each ran three times for Student, Teacher, and Administrator (27 full sign-in cycles total).
**Environment:** Django test client, in-memory SQLite, fictional test users, local in-memory email backend. Firebase SMS verification was mocked; no external provider calls were made.

## Measurements

All values are milliseconds from the first request in the sign-in flow through final successful portal authentication.

| Scenario | Role | Run 1 | Run 2 | Run 3 | Mean |
| --- | --- | ---: | ---: | ---: | ---: |
| Password only | Student | 53.85 | 5.64 | 5.02 | 21.50 |
| Password only | Teacher | 7.16 | 5.37 | 5.29 | 5.94 |
| Password only | Administrator | 4.76 | 4.68 | 4.59 | 4.68 |
| Password + email OTP | Student | 1,278.28 | 14.60 | 14.61 | 435.83 |
| Password + email OTP | Teacher | 13.98 | 16.27 | 18.36 | 16.21 |
| Password + email OTP | Administrator | 12.49 | 12.10 | 12.25 | 12.28 |
| Password + SMS OTP + email step-up | Student | 25.25 | 25.14 | 22.43 | 24.27 |
| Password + SMS OTP + email step-up | Teacher | 23.03 | 23.24 | 23.19 | 23.16 |
| Password + SMS OTP + email step-up | Administrator | 22.20 | 21.90 | 21.86 | 21.99 |

## Limits of this measurement

- These are server-side test-client timings, not browser stopwatch results or production latency.
- SQLite is in memory; the deployed application uses its configured hosted database.
- Email uses Django's in-memory test backend, not Gmail SMTP. SMS sending and Firebase token verification are simulated.
- Preserve all three observations, including the much slower first Student email-OTP run. Do not discard it as an outlier without repeating the measurement under a documented warm/cold-start policy.
- Repeat the same three runs against the configured demonstration environment before presenting these values as deployment performance.

Re-run with `accounts.test_performance` as shown in the Identity Security Test Matrix. The full project test suite also includes these flows and remains the local code-verification source of record.
