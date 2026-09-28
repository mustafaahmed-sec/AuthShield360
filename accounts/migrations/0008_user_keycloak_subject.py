from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0007_password_reset_request_limit")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="keycloak_subject",
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
    ]
