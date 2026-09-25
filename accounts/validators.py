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


class PasswordMaximumLengthValidator:
    """Reject passwords longer than the portal's supported maximum."""

    def __init__(self, max_length=50):
        self.max_length = max_length

    def validate(self, password, user=None):
        if len(password) > self.max_length:
            raise ValidationError(
                f"Password must be no more than {self.max_length} characters.",
                code="password_too_long",
                params={"max_length": self.max_length},
            )

    def get_help_text(self):
        return f"Your password can be up to {self.max_length} characters long."


class RoleBasedPasswordMinimumLengthValidator:
    """Require longer passwords for administrator accounts."""

    def __init__(self, min_length=12, admin_min_length=25):
        self.min_length = min_length
        self.admin_min_length = admin_min_length

    def validate(self, password, user=None):
        minimum = self.admin_min_length if getattr(user, "role", None) == "admin" else self.min_length
        if len(password) < minimum:
            raise ValidationError(
                f"Administrator passwords must be at least {minimum} characters."
                if minimum == self.admin_min_length
                else f"Password must be at least {minimum} characters.",
                code="password_too_short",
                params={"min_length": minimum},
            )

    def get_help_text(self):
        return f"Use at least {self.min_length} characters; Administrator passwords must be at least {self.admin_min_length}."
