#!/bin/sh
set -eu

log() {
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"
}

require_non_empty_env() {
  var_name="${1}"
  eval "var_value=\${${var_name}:-}"
  if [ -z "${var_value}" ]; then
    echo "Missing required environment variable: ${var_name}" >&2
    exit 1
  fi
}

is_positive_integer() {
  case "${1}" in
    ''|*[!0-9]*|0)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

validate_seconds_var() {
  var_name="${1}"
  eval "var_value=\${${var_name}}"
  if ! is_positive_integer "${var_value}"; then
    echo "${var_name} must be a positive integer, got: ${var_value}" >&2
    exit 1
  fi
}

read_current_api_key() {
  sed -n 's/.*<ApiKey>\([^<]*\)<\/ApiKey>.*/\1/p' "${CONFIG_XML}" \
    | head -n 1 \
    | tr -d '\r\n '
}

get_secret_api_key() {
  encoded_key="$(kubectl -n "${NAMESPACE}" get secret "${SECRET_NAME}" \
    -o "go-template={{ index .data \"${SECRET_KEY}\" }}" 2>/dev/null || true)"

  case "${encoded_key}" in
    ''|'<no value>'|'<nil>')
      return 0
      ;;
  esac

  printf '%s' "${encoded_key}" | base64 -d 2>/dev/null || true
}

set_secret_api_key() {
  api_key="${1}"
  encoded_api_key="$(printf '%s' "${api_key}" | base64 | tr -d '\n')"

  if kubectl -n "${NAMESPACE}" patch secret "${SECRET_NAME}" --type=merge -p "{\"data\":{\"${SECRET_KEY}\":\"${encoded_api_key}\"}}" >/dev/null; then
    return 0
  fi

  return 1
}

require_non_empty_env CONFIG_XML
require_non_empty_env NAMESPACE
require_non_empty_env SECRET_NAME
require_non_empty_env SECRET_KEY

: "${FAIL_IF_MISSING:=false}"
: "${WAIT_SECONDS:=2}"
: "${INTERVAL_SECONDS:=30}"
validate_seconds_var WAIT_SECONDS
validate_seconds_var INTERVAL_SECONDS

while [ ! -f "${CONFIG_XML}" ]; do
  log "Waiting for file '${CONFIG_XML}' to exist..."
  sleep 2
done

log "Found file '${CONFIG_XML}'"

LAST_CURRENT_API_KEY="$(read_current_api_key || true)"
LAST_SECRET_API_KEY="$(get_secret_api_key || true)"

while true; do
  CURRENT_API_KEY="$(read_current_api_key || true)"
  if [ -z "${CURRENT_API_KEY}" ]; then
    if [ "${FAIL_IF_MISSING}" = "true" ]; then
      log "ApiKey is missing in '${CONFIG_XML}', exiting due to FAIL_IF_MISSING=true"
      exit 1
    fi
    LAST_CURRENT_API_KEY="${CURRENT_API_KEY}"
    log "Waiting for ApiKey to be present in '${CONFIG_XML}'..."
    sleep "${WAIT_SECONDS}"
    continue
  fi

  SECRET_API_KEY="$(get_secret_api_key || true)"
  if [ "${CURRENT_API_KEY}" != "${SECRET_API_KEY}" ]; then
    if [ -z "${LAST_CURRENT_API_KEY}" ] && [ -z "${LAST_SECRET_API_KEY}" ]; then
      log "ApiKey initialized for the first time"
    elif [ "${CURRENT_API_KEY}" != "${LAST_CURRENT_API_KEY}" ]; then
      log "ApiKey changed in '${CONFIG_XML}'"
    elif [ "${SECRET_API_KEY}" != "${LAST_SECRET_API_KEY}" ]; then
      log "ApiKey changed in Kubernetes secret"
    else
      log "ApiKey changed"
    fi

    if set_secret_api_key "${CURRENT_API_KEY}"; then
      log "Kubernetes secret synchronized"
    else
      log "Failed to patch Kubernetes secret '${SECRET_NAME}', will retry"
    fi
    log "Watching for ApiKey changes..."
  fi

  LAST_CURRENT_API_KEY="${CURRENT_API_KEY}"
  LAST_SECRET_API_KEY="${SECRET_API_KEY}"
  sleep "${INTERVAL_SECONDS}"
done
