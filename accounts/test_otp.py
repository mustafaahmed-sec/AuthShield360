import json
from urllib.error import HTTPError
from urllib.parse import parse_qs
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .otp import OTPProviderError, TwilioVerify


@override_settings(
    TWILIO_API_KEY_SID="SK" + "a" * 32,
    TWILIO_API_KEY_SECRET="test-secret",
    TWILIO_VERIFY_SERVICE_SID="VA" + "b" * 32,
)
class TwilioVerifyAdapterTests(SimpleTestCase):
    def provider_response(self, data):
        patcher = patch("accounts.otp.urlopen")
        response = patcher.start()
        self.addCleanup(patcher.stop)
        response.return_value.__enter__.return_value.read.return_value = json.dumps(data).encode()
        return response

    def test_start_posts_a_whatsapp_verification_to_twilio_verify(self):
        mocked_urlopen = self.provider_response({"status": "pending"})

        TwilioVerify().start("+15550100123", "whatsapp")

        request = mocked_urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/Services/VA" + "b" * 32 + "/Verifications"))
        self.assertEqual(
            parse_qs(request.data.decode()),
            {"To": ["+15550100123"], "Channel": ["whatsapp"]},
        )
        self.assertIsNotNone(request.get_header("Authorization"))

    def test_check_posts_code_and_returns_only_provider_approval(self):
        mocked_urlopen = self.provider_response({"status": "approved", "valid": True})

        valid = TwilioVerify().check("person@example.test", "123456")

        self.assertTrue(valid)
        request = mocked_urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/VerificationCheck"))
        self.assertEqual(
            parse_qs(request.data.decode()),
            {"To": ["person@example.test"], "Code": ["123456"]},
        )

    def test_code_is_rejected_when_provider_has_not_approved_it(self):
        self.provider_response({"status": "pending", "valid": False})

        self.assertFalse(TwilioVerify().check("person@example.test", "123456"))

    def test_expired_twilio_verification_is_reported_as_a_rejected_code(self):
        patcher = patch("accounts.otp.urlopen", side_effect=HTTPError("url", 404, "expired", {}, None))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.assertFalse(TwilioVerify().check("person@example.test", "123456"))

    def test_invalid_whatsapp_destination_is_rejected_before_network_call(self):
        mocked_urlopen = patch("accounts.otp.urlopen")
        urlopen = mocked_urlopen.start()
        self.addCleanup(mocked_urlopen.stop)

        with self.assertRaises(OTPProviderError):
            TwilioVerify().start("555-010-0123", "whatsapp")

        urlopen.assert_not_called()

    def test_start_rejects_a_non_pending_provider_response(self):
        self.provider_response({"status": "failed"})

        with self.assertRaises(OTPProviderError):
            TwilioVerify().start("+15550100123", "whatsapp")
