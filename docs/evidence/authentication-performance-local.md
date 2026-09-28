# SRS authentication performance: local isolated run

**Date:** 2026-09-28
**Command:** `.venv\Scripts\python.exe manage.py test --settings=config.test_settings --verbosity=1` (includes `accounts.test_performance`)
**Test result:** 106 tests passed in 21.33 seconds. The three benchmark scenarios each ran three times for Student, Teacher, and Administrator (27 full sign-in cycles total).
**Environment:** Django test client, in-memory SQLite, fictional test users, local in-memory email backend. Firebase SMS verification was mocked; no external provider calls were made.

## Measurements

All values are milliseconds from the first request in the sign-in flow through final successful portal authentication.

| Scenario | Role | Run 1 | Run 2 | Run 3 | Mean |
| --- | --- | ---: | ---: | ---: | ---: |
| Password only | Student | 54.62 | 6.44 | 4.80 | 21.95 |
| Password only | Teacher | 4.85 | 8.72 | 8.14 | 7.23 |
| Password only | Administrator | 7.38 | 6.73 | 5.56 | 6.56 |
| Password + email OTP | Student | 1,311.42 | 16.64 | 14.36 | 447.47 |
| Password + email OTP | Teacher | 14.36 | 13.83 | 13.82 | 14.01 |
| Password + email OTP | Administrator | 13.37 | 12.33 | 13.02 | 12.91 |
| Password + SMS OTP + email step-up | Student | 26.83 | 24.11 | 25.22 | 25.39 |
| Password + SMS OTP + email step-up | Teacher | 23.74 | 25.42 | 24.54 | 24.57 |
| Password + SMS OTP + email step-up | Administrator | 23.92 | 21.69 | 23.73 | 23.11 |

## Limits of this measurement

- These are server-side test-client timings, not browser stopwatch results or production latency.
- SQLite is in memory; the deployed application uses its configured hosted database.
- Email uses Django's in-memory test backend, not Gmail SMTP. SMS sending and Firebase token verification are simulated.
- Preserve all three observations, including the much slower first Student email-OTP run. Do not discard it as an outlier without repeating the measurement under a documented warm/cold-start policy.
- Repeat the same three runs against the configured demonstration environment before presenting these values as deployment performance.

Re-run with `accounts.test_performance` as shown in the Identity Security Test Matrix. The full project test suite also includes these flows and remains the local code-verification source of record.
