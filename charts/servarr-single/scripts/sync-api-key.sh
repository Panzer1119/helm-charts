#!/bin/sh
set -eu

log() {
  echo "$*"
}

read_current_api_key() {
  sed -n 's/.*<ApiKey>\([^<]*\)<\/ApiKey>.*/\1/p' "${CONFIG_XML}" \
    | head -n 1 \
    | tr -d '\r\n '
}

get_secret_api_key() {
  kubectl -n "${NAMESPACE}" get secret "${SECRET_NAME}" \
    -o jsonpath="{.data.${SECRET_KEY}}" 2>/dev/null \
  | base64 -d 2>/dev/null || true
}

set_secret_api_key() {
  api_key="${1}"

  kubectl -n "${NAMESPACE}" patch secret "${SECRET_NAME}" --type=merge -p "{
    \"data\": {
      \"${SECRET_KEY}\": \"$(printf '%s' "${api_key}" | base64 | tr -d '\n')\"
    }
  }" >/dev/null
}

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
      log "ApiKey changed, but unable to determine source of change"
    fi
    set_secret_api_key "${CURRENT_API_KEY}"
    log "Kubernetes secret synchronized"
  fi

  LAST_CURRENT_API_KEY="${CURRENT_API_KEY}"
  LAST_SECRET_API_KEY="${SECRET_API_KEY}"
  log "Watching for ApiKey changes..."
  sleep "${INTERVAL_SECONDS}"
done
