#!/bin/sh
# ------------------------------------------------------------------------------
# This helper prints a recommended "SYNC_TRAVERSAL_WORKERS" value.
# ------------------------------------------------------------------------------

set -eu

# ------------------------------------------------------------------------------
# This function reads CPU count from an optional argument or the host.
#
# 1. "${1:-}" is an optional positive integer CPU count override.
#
# Returns: Positive integer CPU count written to stdout.
#
# N.B.
# The function exits non-zero when the provided override is not a positive
# integer.
# ------------------------------------------------------------------------------
getCpuCount() {
  RAW_COUNT="${1:-}"

  if [ -n "$RAW_COUNT" ]; then
    case "$RAW_COUNT" in
      ''|*[!0-9]*)
        echo "CPU count must be a positive integer." >&2
        exit 1
        ;;
    esac

    if [ "$RAW_COUNT" -lt 1 ]; then
      echo "CPU count must be a positive integer." >&2
      exit 1
    fi

    printf '%s\n' "$RAW_COUNT"
    return 0
  fi

  if command -v getconf >/dev/null 2>&1; then
    DETECTED_COUNT="$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
  else
    DETECTED_COUNT=""
  fi

  case "$DETECTED_COUNT" in
    ''|*[!0-9]*)
      DETECTED_COUNT=1
      ;;
  esac

  if [ "$DETECTED_COUNT" -lt 1 ]; then
    DETECTED_COUNT=1
  fi

  printf '%s\n' "$DETECTED_COUNT"
}

# ------------------------------------------------------------------------------
# This function converts CPU count into a bounded traversal-worker value.
#
# 1. "${1:?}" is detected CPU count as a positive integer.
#
# Returns: Recommended "SYNC_TRAVERSAL_WORKERS" value from "1" to "8".
# ------------------------------------------------------------------------------
getRecommendedTraversalWorkers() {
  CPU_COUNT="${1:?}"

  if [ "$CPU_COUNT" -gt 8 ]; then
    printf '8\n'
    return 0
  fi

  printf '%s\n' "$CPU_COUNT"
}

CPU_COUNT="$(getCpuCount "${1:-}")"
RECOMMENDED_WORKERS="$(getRecommendedTraversalWorkers "$CPU_COUNT")"

printf 'Detected CPU count: %s\n' "$CPU_COUNT"
printf 'Recommended SYNC_TRAVERSAL_WORKERS=%s\n' "$RECOMMENDED_WORKERS"
