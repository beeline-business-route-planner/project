#!/usr/bin/env bash
set -euo pipefail
# The pinned image has bash, but neither curl nor wget.
exec 3<>/dev/tcp/127.0.0.1/5000
printf 'GET /nearest/v1/driving/%s HTTP/1.0\r\nHost: localhost\r\n\r\n' "${OSRM_HEALTH_COORDINATE:-37.6173,55.7558}" >&3
read -r status <&3
[[ "$status" == *' 200 '* ]]
