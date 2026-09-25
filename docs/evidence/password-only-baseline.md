# Password-only baseline: preliminary local run

**Date:** 2026-09-25
**Target:** `http://127.0.0.1:8000/` (local only)
**Status:** Partial; do not treat this as the team's complete SRS baseline.

## Checks completed

Temporary fictional accounts were created inside a database transaction and rolled back after the checks. No temporary accounts, sessions, or test audit events were retained.

| Check | Result |
| --- | --- |
| Student sign-in, 3 runs | 3/3 passed; 502.8, 447.9, 461.5 ms; mean 470.7 ms |
| Teacher sign-in, 3 runs | 3/3 passed; 506.1, 463.3, 449.4 ms; mean 472.9 ms |
| Administrator sign-in, 3 runs | 3/3 passed; 721.1, 651.4, 746.2 ms; mean 706.2 ms |
| Wrong passwords | 3/3 rejected; no sessions created |
| Known test password replay | Accepted with password alone, as expected for this baseline stage |
| Student opening Teacher page | HTTP 403 |
| Teacher opening Administrator page | HTTP 403 |
| Reusing a session after logout | Rejected; redirected to sign-in |
| Local home and sign-in pages | HTTP 200 |
| `GET /logout/` | HTTP 405; logout is POST-only |
| Browser view | Local landing page and responsive navigation displayed |
| Browser security response checks | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`; no Content-Security-Policy header |
| Session cookie | HttpOnly and SameSite=Lax; Secure=false on the local HTTP/debug site |
| JavaScript syntax and delivery | `node --check` passed; local script returned HTTP 200 |

The login timings use Django's local test client and the configured local database/password hasher. They are server-side request measurements, not three human stopwatch measurements in a browser.

## Not completed

- The configured local demo passwords did not match the stored password hashes for the Student, Teacher, or Administrator primary demo accounts. I left all passwords unchanged. The successful timing and access checks above therefore used temporary test accounts.
- No ZAP or Burp scan was run. Kali is registered in VirtualBox but is not running; its network adapter is bridged, while the local portal listens only on `127.0.0.1`. I did not expose the portal on the network to make the scan reachable.
- The browser's developer console was not accessible through the available browser controls. The page was visually checked and its local HTTP responses and assets were inspected.

**Next:** fix the local demo-account credential mismatch and run the ZAP/Burp plus browser DevTools checks against the local portal. Then record the team's baseline results before starting Part 3.
