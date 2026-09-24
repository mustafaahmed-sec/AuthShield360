"""Keep the public production alias from bypassing Vercel's demo protection."""

import os

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect


class ProtectedDemoRedirectMiddleware:
    """Send the public alias to this deployment's Vercel protected URL."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.DEBUG and settings.AUTHSHIELD_PROTECTED_DEMO:
            public_host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", "authshield360.vercel.app")
            if request.get_host().split(":", 1)[0].lower() == public_host.lower():
                deployment_host = os.environ.get("VERCEL_URL", "").lower().strip()
                if (
                    deployment_host.endswith(".vercel.app")
                    and "/" not in deployment_host
                    and ":" not in deployment_host
                    and deployment_host != public_host.lower()
                ):
                    return HttpResponseRedirect(f"https://{deployment_host}{request.get_full_path()}")
                return HttpResponse("Protected demo URL unavailable.", status=503)
        return self.get_response(request)
