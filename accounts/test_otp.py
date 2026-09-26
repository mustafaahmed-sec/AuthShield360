from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from google.auth.exceptions import GoogleAuthError

from .otp import OTPProviderError, normalize_phone_number, verify_firebase_phone_id_token


@override_settings(
    AUTHSHIELD_FIREBASE_API_KEY="test-web-api-key",
    AUTHSHIELD_FIREBASE_AUTH_DOMAIN="authshield-test.firebaseapp.com",
    AUTHSHIELD_FIREBASE_PROJECT_ID="authshield-test",
    AUTHSHIELD_FIREBASE_APP_ID="1:123:web:test",
)
class FirebasePhoneAuthTests(SimpleTestCase):
    def claims(self, **overrides):
        claims = {
            "aud": "authshield-test",
            "auth_time": 101,
            "phone_number": "+923001234567",
            "firebase": {"sign_in_provider": "phone"},
        }
        claims.update(overrides)
        return claims

    def test_pakistani_phone_input_is_normalized_to_e164(self):
        self.assertEqual(normalize_phone_number("0300 1234567"), "+923001234567")
        self.assertEqual(normalize_phone_number("+92 (300) 123-4567"), "+923001234567")
        self.assertEqual(normalize_phone_number("not a phone"), "")

    def test_valid_fresh_phone_token_is_returned_for_expected_project_and_number(self):
        with patch("accounts.otp.verify_firebase_token", return_value=self.claims()) as verify:
            claims = verify_firebase_phone_id_token(
                "signed-token", expected_phone="+923001234567", minimum_auth_time=100,
            )

        self.assertIsNotNone(claims)
        verify.assert_called_once()
        self.assertEqual(verify.call_args.kwargs["audience"], "authshield-test")

    def test_wrong_phone_provider_or_stale_token_is_rejected(self):
        cases = (
            self.claims(phone_number="+923001234568"),
            self.claims(firebase={"sign_in_provider": "password"}),
            self.claims(auth_time=50),
        )
        for claims in cases:
            with self.subTest(claims=claims), patch("accounts.otp.verify_firebase_token", return_value=claims):
                self.assertIsNone(verify_firebase_phone_id_token(
                    "signed-token", expected_phone="+923001234567", minimum_auth_time=100,
                ))

    def test_invalid_token_is_rejected_and_google_verifier_outage_is_reported(self):
        with patch("accounts.otp.verify_firebase_token", side_effect=ValueError("invalid token")):
            self.assertIsNone(verify_firebase_phone_id_token(
                "bad-token", expected_phone="+923001234567", minimum_auth_time=100,
            ))
        with patch("accounts.otp.verify_firebase_token", side_effect=GoogleAuthError("offline")):
            with self.assertRaises(OTPProviderError):
                verify_firebase_phone_id_token(
                    "signed-token", expected_phone="+923001234567", minimum_auth_time=100,
                )
