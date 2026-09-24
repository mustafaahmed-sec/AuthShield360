# Local restart and demo reset procedure

This procedure is for the local demonstration only. It does not require a reset, migration, or write to the hosted Vercel/Neon database. Never run `seed_demo --reset` against a database that contains real users or data you need to keep.

## Check persistence across an application restart

1. Start the local portal using the project's local `.env` and sign in as a demo Administrator.
2. Note the visible Student, Teacher, and Administrator totals. Open the recent activity list and confirm the current login appears with its time, account, role, factor, outcome, and observed IP.
3. Stop only the local Django development server with `Ctrl+C`. Do not stop PostgreSQL.
4. Start the local server again with `python manage.py runserver 127.0.0.1:8000` from the project folder.
5. Sign in again. Confirm the roster totals and the earlier audit event still appear. This demonstrates persistence across an application-process restart; the automated session test separately confirms that a logged-out browser session cannot be restored by replaying its old cookie.

## Prove a repeatable seed reset safely

Use a separate disposable local database that contains only generated demo records. First confirm its database name in a local-only `.env` and verify that the portal is not connected to Neon or any other hosted database. Back up or discard the disposable database before continuing.

From the project folder, run:

```powershell
python manage.py migrate
python manage.py seed_demo --reset
python manage.py seed_demo
python manage.py seed_demo
```

Confirm the result is 486 Student accounts, 32 Teacher accounts, and 3 Administrator accounts, with no duplicate generated roster or enrollments. Repeat the count check after stopping and restarting the local Django server. The reset is intended to remove and rebuild generated `demo.*` accounts and their associated demo records; it retains the primary demo accounts. Do not use this procedure on a shared, production, or hosted database.

For an automated, disposable check that cannot touch the configured PostgreSQL database, run:

```powershell
python manage.py test school.test_seed_demo --settings=config.test_settings
```

That test settings module uses an isolated in-memory SQLite database.
