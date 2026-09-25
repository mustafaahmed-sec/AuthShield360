from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_user_locked_until"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="designation",
            field=models.CharField(
                blank=True,
                choices=[
                    ("school_director", "School Director"),
                    ("principal", "Principal"),
                    ("assistant_principal", "Assistant Principal"),
                ],
                default="",
                max_length=32,
            ),
        ),
    ]
