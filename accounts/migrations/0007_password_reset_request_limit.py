from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_email_otp_challenge"),
    ]

    operations = [
        migrations.CreateModel(
            name="PasswordResetRequestLimit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fingerprint", models.CharField(max_length=64, unique=True)),
                ("window_started_at", models.DateTimeField()),
                ("request_count", models.PositiveSmallIntegerField(default=0)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["window_started_at"], name="pwd_reset_limit_window_idx"),
                ],
            },
        ),
    ]
