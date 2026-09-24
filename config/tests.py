from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .middleware import ProtectedDemoRedirectMiddleware


class ProtectedDemoRedirectTests(SimpleTestCase):
    @override_settings(DEBUG=False, AUTHSHIELD_PROTECTED_DEMO=True)
    @patch.dict(
        "os.environ",
        {
            "VERCEL_PROJECT_PRODUCTION_URL": "authshield360.vercel.app",
            "VERCEL_URL": "authshield360-unique.vercel.app",
        },
    )
    def test_public_alias_redirects_to_protected_deployment(self):
        middleware = ProtectedDemoRedirectMiddleware(lambda request: HttpResponse("portal"))
        request = RequestFactory().get("/signup/student/?page=1", HTTP_HOST="authshield360.vercel.app")

        response = middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://authshield360-unique.vercel.app/signup/student/?page=1",
        )

    @override_settings(DEBUG=False, AUTHSHIELD_PROTECTED_DEMO=True)
    @patch.dict("os.environ", {"VERCEL_URL": ""})
    def test_public_alias_fails_closed_without_deployment_url(self):
        middleware = ProtectedDemoRedirectMiddleware(lambda request: HttpResponse("portal"))
        request = RequestFactory().get("/", HTTP_HOST="authshield360.vercel.app")

        self.assertEqual(middleware(request).status_code, 503)
