from django.core.exceptions import ValidationError


class PasswordCharacterSetValidator:
    """Require lower/upper case, a digit, and a non-space symbol."""

    def validate(self, password, user=None):
        requirements = (
            (any(char.islower() for char in password), "a lowercase letter"),
            (any(char.isupper() for char in password), "an uppercase letter"),
            (any(char.isdigit() for char in password), "a number"),
            (any(not char.isalnum() and not char.isspace() for char in password), "a special character"),
        )
        missing = [label for present, label in requirements if not present]
        if missing:
            raise ValidationError(
                "Password must include at least " + ", ".join(missing) + ".",
                code="password_character_set",
            )

    def get_help_text(self):
        return "Include at least one lowercase letter, one uppercase letter, one number, and one special character."
