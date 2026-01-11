#!/bin/sh
set -eu

LAST_KEY=""

extract_api_key() {
  sed -n 's/.*<ApiKey>\([^<]*\)<\/ApiKey>.*/\1/p' "${CONFIG_XML}" \
    | head -n 1 \
    | tr -d '\r\n '
}

get_secret_key() {
  kubectl -n "${NAMESPACE}" get secret "${SECRET_NAME}" \
    -o jsonpath="{.data.${SECRET_KEY}}" 2>/dev/null \
  | base64 -d 2>/dev/null || true
}

update_secret() {
  api_key="${1}"

  kubectl -n "${NAMESPACE}" patch secret "${SECRET_NAME}" --type=merge -p "{
    \"data\": {
      \"${SECRET_KEY}\": \"$(printf '%s' "${api_key}" | base64 | tr -d '\n')\"
    }
  }"
}

echo "Waiting for config.xml..."

while [ ! -f "${CONFIG_XML}" ]; do
  sleep 2
done

echo "config.xml found, initializing state"

# Initialize LAST_KEY from the existing secret
LAST_KEY="$(get_secret_key || true)"

if API_KEY="$(extract_api_key)" && [ -n "${API_KEY}" ]; then
  if [ "${API_KEY}" != "${LAST_KEY}" ]; then
    echo "Initial ApiKey differs from Secret, syncing"
    update_secret "${API_KEY}"
    LAST_KEY="${API_KEY}"
  else
    echo "Secret already up to date"
  fi
else
  echo "ApiKey not present yet; waiting for changes"
fi

echo "Entering watch loop"

while true; do
  inotifywait -q -e modify,create,move "${CONFIG_XML}"

  API_KEY="$(extract_api_key || true)"

  if [ -z "${API_KEY}" ]; then
    echo "ApiKey missing; ignoring update"
    continue
  fi

  if [ "${API_KEY}" = "${LAST_KEY}" ]; then
    continue
  fi

  echo "ApiKey changed, updating Secret"
  update_secret "${API_KEY}"
  LAST_KEY="${API_KEY}"
done
