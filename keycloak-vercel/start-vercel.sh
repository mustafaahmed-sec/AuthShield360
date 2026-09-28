#!/usr/bin/env bash
set -euo pipefail

: "${KC_HOSTNAME:?Set KC_HOSTNAME to the stable public HTTPS URL}"
# The Vercel Neon integration uses a KC_DB_ prefix. Prefer its direct URL
# for Keycloak's long-lived JDBC connections and schema initialization.
KC_DB_URL="${KC_DB_URL:-${KC_DB_DATABASE_URL_UNPOOLED:-${KC_DB_POSTGRES_URL_NON_POOLING:-${KC_DB_DATABASE_URL:-}}}}"
: "${KC_DB_URL:?Set KC_DB_URL to the dedicated PostgreSQL connection URL}"
: "${KC_BOOTSTRAP_ADMIN_USERNAME:?Set KC_BOOTSTRAP_ADMIN_USERNAME in Vercel}"
: "${KC_BOOTSTRAP_ADMIN_PASSWORD:?Set KC_BOOTSTRAP_ADMIN_PASSWORD in Vercel}"

decode_uri_component() {
  local input="$1" output="" prefix hex decoded
  while [[ "$input" == *%* ]]; do
    prefix="${input%%\%*}"
    output+="$prefix"
    input="${input#*\%}"
    if [[ "${#input}" -lt 2 ]]; then
      output+="%${input}"
      input=""
      break
    fi
    hex="${input:0:2}"
    if [[ "$hex" =~ ^[[:xdigit:]]{2}$ ]]; then
      printf -v decoded '%b' "\\x${hex}"
      output+="$decoded"
      input="${input:2}"
    else
      output+="%"
    fi
  done
  printf '%s%s' "$output" "$input"
}

# Vercel's Neon integration supplies a standard PostgreSQL URI. Keycloak
# expects JDBC plus separate credentials, so translate it only in process
# memory and never print the connection details.
if [[ "$KC_DB_URL" == postgres://* || "$KC_DB_URL" == postgresql://* ]]; then
  postgres_uri="${KC_DB_URL#*://}"
  authority="${postgres_uri%%/*}"
  database_query="${postgres_uri#*/}"
  if [[ "$authority" == "$postgres_uri" || "$authority" != *@* || "$authority" != *:* ]]; then
    echo "KC_DB_URL must include a PostgreSQL username, password, host, and database." >&2
    exit 1
  fi

  credentials="${authority%@*}"
  database_host="${authority##*@}"
  encoded_username="${credentials%%:*}"
  encoded_password="${credentials#*:}"
  database_name="${database_query%%\?*}"
  if [[ -z "$database_host" || -z "$database_name" || "$encoded_password" == "$credentials" ]]; then
    echo "KC_DB_URL is missing required PostgreSQL connection parts." >&2
    exit 1
  fi

  export KC_DB_USERNAME="${KC_DB_USERNAME:-$(decode_uri_component "$encoded_username")}"
  if [[ -z "${KC_DB_PASSWORD:-}" && -z "${KCRAW_DB_PASSWORD:-}" ]]; then
    export KCRAW_DB_PASSWORD="$(decode_uri_component "$encoded_password")"
  fi
  export KC_DB_URL="jdbc:postgresql://${database_host}/$(decode_uri_component "$database_name")?sslmode=require"
fi

: "${KC_DB_USERNAME:?Set KC_DB_USERNAME or connect the Neon PostgreSQL URL}"
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
