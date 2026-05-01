#!/bin/sh
# ------------------------------------------------------------------------------
# This script verifies healthcheck behaviour in a built container image.
#
# It proves the runtime contract that source-level tests alone cannot cover:
#
# 1. The built image uses shell-invoked Docker healthchecks.
# 2. A fresh heartbeat file passes the healthcheck.
# 3. A stale heartbeat file fails the healthcheck.
# 4. A missing heartbeat file fails the healthcheck.
# ------------------------------------------------------------------------------

set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
IMAGE_TAG="${1:-pyiclodoc-drive:healthcheck-test}"
CONTAINER_NAME="pyiclodoc-drive-healthcheck-test-$$"

# ------------------------------------------------------------------------------
# This function prints an error message and exits non-zero.
#
# 1. "${1:?}" is the error message to print.
# ------------------------------------------------------------------------------
failCheck() {
  printf '%s\n' "${1:?}" >&2
  exit 1
}

# ------------------------------------------------------------------------------
# This function removes the temporary verification container on exit.
# ------------------------------------------------------------------------------
cleanupContainer() {
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}

trap cleanupContainer EXIT INT TERM

command -v docker >/dev/null 2>&1 || failCheck "docker is required"

ALP_VER="$(awk -F= '/^ALP_VER=/{print $2}' "${REPO_ROOT}/.env.example")"
MCK_VER="$(awk -F= '/^MCK_VER=/{print $2}' "${REPO_ROOT}/.env.example")"

docker build \
  --build-arg "ALP_VER=${ALP_VER}" \
  --build-arg "MCK_VER=${MCK_VER}" \
  --tag "${IMAGE_TAG}" \
  "${REPO_ROOT}"

HEALTHCHECK_TEST="$(
  docker image inspect "${IMAGE_TAG}" \
    --format '{{json .Config.Healthcheck.Test}}'
)"

[ "${HEALTHCHECK_TEST}" = '["CMD","sh","/app/scripts/healthcheck.sh"]' ] || \
  failCheck "image healthcheck command did not match expected shell invocation"

docker run \
  --detach \
  --name "${CONTAINER_NAME}" \
  --entrypoint sh \
  "${IMAGE_TAG}" \
  -c 'sleep 300' >/dev/null

docker exec "${CONTAINER_NAME}" sh -c '
  mkdir -p /logs
  : > /logs/pyiclodoc-drive-heartbeat.txt
'

docker exec "${CONTAINER_NAME}" sh -c \
  'sh /app/scripts/healthcheck.sh'

docker exec "${CONTAINER_NAME}" python3 -c '
import os
import time
PATH = "/logs/pyiclodoc-drive-heartbeat.txt"
OLD_EPOCH = time.time() - 70
os.utime(PATH, (OLD_EPOCH, OLD_EPOCH))
'

if docker exec "${CONTAINER_NAME}" sh -c \
  'sh /app/scripts/healthcheck.sh'
then
  failCheck "stale heartbeat unexpectedly passed healthcheck"
fi

docker exec "${CONTAINER_NAME}" sh -c \
  'rm -f /logs/pyiclodoc-drive-heartbeat.txt'

if docker exec "${CONTAINER_NAME}" sh -c \
  'sh /app/scripts/healthcheck.sh'
then
  failCheck "missing heartbeat unexpectedly passed healthcheck"
fi

printf '%s\n' "Image healthcheck verification passed."
