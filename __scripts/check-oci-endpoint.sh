#!/usr/bin/env bash

# Run on the server that hosts the backend. Usage: check-oci-endpoint.sh [region]
region=${1:-ap-tokyo-1}
if [[ $# -gt 1 || ! $region =~ ^[a-z]+(-[a-z0-9]+)+-[0-9]+$ ]]; then
    printf 'Usage: %s [region]\n' "$0" >&2
    exit 2
fi

# Any HTTP status confirms a response. HTTP 000 indicates no HTTP response.
status=0
for host in \
    "agent-runtime.generativeai.$region.oraclecloud.com" \
    "agent-runtime.generativeai.$region.oci.oraclecloud.com"
do
    printf '\n%s\n' "$host"
    curl -sS -o /dev/null -w 'HTTP %{http_code}\n' \
        --connect-timeout 5 --max-time 15 "https://$host/" || status=1
done
exit "$status"
