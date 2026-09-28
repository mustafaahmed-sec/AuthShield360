# Deploy Keycloak for AuthShield 360 on Vercel

This folder is a separate Vercel container project. It leaves the existing Django portal project and its Vercel configuration untouched. Vercel builds it from GitHub when this folder is selected as the project's **Root Directory**.

## Important deployment note

Vercel Container Images are currently in Beta and scale down after periods without traffic. This image enables Keycloak's `stateless` mode so authentication-flow state is stored in PostgreSQL rather than only in a short-lived container cache. Keycloak labels that mode as Preview. This makes the Vercel setup suitable for evaluation and a controlled demonstration, but it is not the conservative choice for a school identity service that must be continuously available. For that production requirement, run this same container on an always-on container host with a supported Keycloak topology instead.

Use a managed PostgreSQL database with backups and TLS. Give Keycloak a dedicated database (or at minimum a dedicated schema and database user); do not point it at the Django portal's application schema. Never commit database credentials, Keycloak admin credentials, or the OIDC client secret.

## Create the Vercel project

1. Push this folder to the AuthShield GitHub repository.
2. In Vercel, choose **Add New → Project**, import the same GitHub repository, and create a separate project named for Keycloak.
3. Set **Root Directory** to `keycloak-vercel` and leave the portal's existing Vercel project alone.
4. Give this project a stable domain, such as a Vercel project domain or a custom domain. Set `KC_HOSTNAME` to its full `https://` URL (no trailing slash).
5. Add the environment variables below to **Production** and **Preview** as appropriate. Mark passwords as sensitive. Set `PORT` to `8080`.
6. Deploy. Later GitHub pushes to the selected production branch will create deployments for this Keycloak Vercel project.

### Required Vercel environment variables

| Name | Value |
| --- | --- |
| `PORT` | `8080` |
| `KC_HOSTNAME` | `https://<your-keycloak-domain>` |
| `KC_DB_URL` | `jdbc:postgresql://<database-host>:5432/<database-name>?sslmode=require` |
| `KC_DB_USERNAME` | Dedicated Keycloak PostgreSQL user |
| `KC_DB_PASSWORD` | Dedicated PostgreSQL password; if it contains `$`, use `KCRAW_DB_PASSWORD` instead |
| `KC_BOOTSTRAP_ADMIN_USERNAME` | A new, private Keycloak administrator username |
| `KC_BOOTSTRAP_ADMIN_PASSWORD` | A long, unique Keycloak administrator password |

`KC_DB=postgres`, HTTP behind the Vercel TLS proxy, forwarded-header handling, and strict hostname validation are set in the image. Do not add `start-dev` or turn off hostname validation.

## Configure the Keycloak realm and portal client

After the first deployment, open `https://<your-keycloak-domain>/admin/` and sign in with the bootstrap administrator. Create a realm named `authshield` and a confidential OpenID Connect client:

- Client ID: `authshield-portal`
- Client authentication: **On**
- Standard flow: **On**
- Valid redirect URI: `https://authshield360.vercel.app/login/keycloak/callback/`
- Web origin: the exact portal origin, for example `https://authshield360.vercel.app`

In **Realm Settings → Email**, configure the SMTP account that will send Keycloak email verification and password-reset messages. In **Realm Settings → Login**, enable user registration and email verification and require unique email addresses. Keep Keycloak's own phone/SMS OTP turned off; the portal uses Firebase Phone Auth for the SMS step-up.

Copy the client secret from the client credentials page. Set these variables on the **existing AuthShield Django portal Vercel project**, not on this Keycloak project:

```text
AUTHSHIELD_KEYCLOAK_ENABLED=true
AUTHSHIELD_KEYCLOAK_SERVER_URL=https://<your-keycloak-domain>
AUTHSHIELD_KEYCLOAK_REALM=authshield
AUTHSHIELD_KEYCLOAK_CLIENT_ID=authshield-portal
AUTHSHIELD_KEYCLOAK_CLIENT_SECRET=<client-secret>
```

Keep the portal's existing Firebase OTP settings enabled. Apply the portal database migration for `accounts.User.keycloak_subject` before enabling Keycloak in the live portal. The Django app still owns school-role approval and Firebase phone verification; Keycloak supplies identity and password sign-in.

For the portal's optional Keycloak account-management synchronization, create a second confidential client with service accounts enabled, grant only the realm `manage-users` role required by the current integration, and add `AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_ID` and `AUTHSHIELD_KEYCLOAK_ADMIN_CLIENT_SECRET` to the portal's Vercel environment. This is optional for sign-in; without it, account-management actions that affect Keycloak must be performed in the Keycloak Admin Console.

If you attach a custom Keycloak domain later, update `KC_HOSTNAME`, deploy this project again, update `AUTHSHIELD_KEYCLOAK_SERVER_URL` in the portal project, and ensure the client redirect URI still exactly matches the portal callback.

## Limitations

- Stateless Keycloak mode is Preview and increases PostgreSQL work for authentication flows.
- Vercel may cold-start the service after idle time; the first identity redirect can therefore be slower.
- A Vercel container deployment does not replace a resilient Keycloak cluster. Validate real login, logout, registration, recovery email, portal callback, Firebase OTP, and database recovery behavior before relying on it for real school accounts.
- The initial Keycloak bootstrap credentials are for setup only. Create a separate named administrator account, secure it, and remove or rotate the bootstrap account credentials after initial provisioning according to Keycloak's bootstrap-account guidance.

## References

- [Vercel Container Images](https://vercel.com/docs/functions/container-images)
- [Keycloak container guide](https://www.keycloak.org/server/containers)
- [Keycloak production configuration](https://www.keycloak.org/server/configuration-production)
- [Keycloak stateless mode preview](https://www.keycloak.org/2026/07/multi-cluster-v2-and-stateless-mode)
