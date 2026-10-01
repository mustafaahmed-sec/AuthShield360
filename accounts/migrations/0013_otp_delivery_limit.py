from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_keycloakmfapolicy_rolemfapolicy"),
    ]

    operations = [
        migrations.CreateModel(
            name="OTPDeliveryLimit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("channel", models.CharField(choices=[("email", "Email"), ("sms", "SMS")], max_length=8)),
                ("last_requested_at", models.DateTimeField(blank=True, null=True)),
                ("request_count", models.PositiveSmallIntegerField(default=0)),
                ("locked_until", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="otp_delivery_limits", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="otpdeliverylimit",
            constraint=models.UniqueConstraint(fields=("user", "channel"), name="unique_user_otp_delivery_channel"),
        ),
    ]
