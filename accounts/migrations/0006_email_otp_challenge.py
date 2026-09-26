from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0005_user_must_change_password"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailOTPChallenge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("purpose", models.CharField(choices=[("sign_in", "Sign in"), ("email_step_up", "Additional sign-in verification"), ("password_reset", "Password reset")], max_length=24)),
                ("code_hash", models.CharField(blank=True, default="", max_length=128)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="email_otp_challenges", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("user", "purpose"), name="unique_user_email_otp_purpose"),
                ],
            },
        ),
    ]
