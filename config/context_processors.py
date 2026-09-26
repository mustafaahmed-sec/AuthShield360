import os

def static_version(request):
    """Give browsers a new asset URL whenever Vercel builds a new commit."""
    revision = (
        os.environ.get("VERCEL_GIT_COMMIT_SHA", "").strip()
        or os.environ.get("VERCEL_URL", "").strip()
        or "local"
    )
    return {"static_version": revision[:12]}
