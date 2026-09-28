#!/usr/bin/env bash
set -euo pipefail

: "${KC_HOSTNAME:?Set KC_HOSTNAME to this Keycloak deployment's stable HTTPS URL}"
: "${KC_DB_URL:?Set KC_DB_URL to the dedicated PostgreSQL JDBC URL}"
: "${KC_DB_USERNAME:?Set KC_DB_USERNAME to the Keycloak database user}"
: "${KC_BOOTSTRAP_ADMIN_USERNAME:?Set KC_BOOTSTRAP_ADMIN_USERNAME in Vercel}"
: "${KC_BOOTSTRAP_ADMIN_PASSWORD:?Set KC_BOOTSTRAP_ADMIN_PASSWORD in Vercel}"
if [[ -z "${KC_DB_PASSWORD:-}" && -z "${KCRAW_DB_PASSWORD:-}" ]]; then
  echo "Set KC_DB_PASSWORD (or KCRAW_DB_PASSWORD if it contains dollar signs) in Vercel." >&2
  exit 1
fi
case "${KC_HOSTNAME}" in
  https://*) ;;
  *) echo "KC_HOSTNAME must use HTTPS and the stable public domain." >&2; exit 1 ;;
esac

# Vercel's default container port is 80. Configure PORT=8080 in the Vercel
# project settings to avoid binding a privileged port as Keycloak's non-root user.
export KC_HTTP_PORT="${PORT:-8080}"

exec /opt/keycloak/bin/kc.sh start \
  --optimized \
  --hostname="${KC_HOSTNAME}" \
  --proxy-headers=xforwarded \
  --spi-cache-embedded--default--cluster-name=authshield-vercel
