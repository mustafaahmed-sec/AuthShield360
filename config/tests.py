from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .middleware import CanonicalProductionHostMiddleware
from .settings import _same_database_target


class PreviewDatabaseIsolationTests(SimpleTestCase):
    def test_postgres_url_scheme_aliases_cannot_bypass_database_isolation(self):
        self.assertTrue(
            _same_database_target(
                "postgres://preview@ep-demo-pooler.us-east-2.aws.neon.tech/school",
                "postgresql://production@EP-DEMO.us-east-2.aws.neon.tech:5432/school/",
            )
        )

    def test_different_database_name_is_a_separate_target(self):
        self.assertFalse(
            _same_database_target(
                "postgres://preview@db.example.test/school_preview",
                "postgresql://production@db.example.test/school",
            )
        )


class ProductionHostMiddlewareTests(SimpleTestCase):
    @override_settings(
        DEBUG=False,
        AUTHSHIELD_PROTECTED_DEMO=True,
        ALLOWED_HOSTS=["testserver", "authshield360.vercel.app", "authshield360-unique.vercel.app"],
    )
    @patch.dict(
        "os.environ",
        {
            "VERCEL_PROJECT_PRODUCTION_URL": "authshield360.vercel.app",
            "VERCEL_URL": "authshield360-unique.vercel.app",
            "VERCEL_ENV": "production",
        },
    )
    def test_stable_alias_serves_the_current_release_without_redirecting(self):
        middleware = CanonicalProductionHostMiddleware(lambda request: HttpResponse("portal"))
        request = RequestFactory().get("/signup/student/?page=1", HTTP_HOST="authshield360.vercel.app")

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)
        self.assertIn("no-store", response["Cache-Control"])


    @override_settings(
        DEBUG=False,
        AUTHSHIELD_PROTECTED_DEMO=True,
        ALLOWED_HOSTS=["testserver", "authshield360.vercel.app", "authshield360-unique.vercel.app"],
    )
    @patch.dict(
        "os.environ",
        {
            "VERCEL_PROJECT_PRODUCTION_URL": "authshield360.vercel.app",
            "VERCEL_URL": "authshield360-unique.vercel.app",
            "VERCEL_ENV": "production",
        },
    )
    def test_production_deployment_url_redirects_to_the_stable_alias(self):
        middleware = CanonicalProductionHostMiddleware(lambda request: HttpResponse("portal"))
        request = RequestFactory().get("/signup/student/?page=1", HTTP_HOST="authshield360-unique.vercel.app")

        response = middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://authshield360.vercel.app/signup/student/?page=1",
        )
        self.assertIn("no-store", response["Cache-Control"])
