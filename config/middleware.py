"""Keep production traffic on its stable alias and prevent stale HTML caches."""

import os

from django.conf import settings
from django.http import HttpResponseRedirect


class CanonicalProductionHostMiddleware:
    """Canonicalize production deployment URLs to the stable project domain."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        public_host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", "authshield360.vercel.app").lower().strip()
        deployment_host = os.environ.get("VERCEL_URL", "").lower().strip()
        request_host = request.get_host().split(":", 1)[0].lower()
        is_production_deployment = os.environ.get("VERCEL_ENV", "").lower() == "production"

        if (
            not settings.DEBUG
            and is_production_deployment
            and request_host != public_host
            and request_host == deployment_host
            and deployment_host.endswith(".vercel.app")
            and "/" not in deployment_host
        ):
            response = HttpResponseRedirect(f"https://{public_host}{request.get_full_path()}")
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response

        response = self.get_response(request)
        if response.get("Content-Type", "").startswith("text/html"):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response
