#!/bin/sh
# ------------------------------------------------------------------------------
# This helper prints a recommended "SYNC_TRAVERSAL_WORKERS" value.
# ------------------------------------------------------------------------------

set -eu

PROC_CPUINFO_PATH="${PROC_CPUINFO_PATH:-/proc/cpuinfo}"

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

  if command -v nproc >/dev/null 2>&1; then
    DETECTED_COUNT="$(nproc 2>/dev/null || true)"
    if isPositiveInteger "$DETECTED_COUNT"; then
      printf '%s\n' "$DETECTED_COUNT"
      return 0
    fi
  fi

  if command -v getconf >/dev/null 2>&1; then
    DETECTED_COUNT="$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
    if isPositiveInteger "$DETECTED_COUNT"; then
      printf '%s\n' "$DETECTED_COUNT"
      return 0
    fi
  fi

  if [ -r "$PROC_CPUINFO_PATH" ]; then
    DETECTED_COUNT="$(grep -c '^processor[[:space:]]*:' "$PROC_CPUINFO_PATH" 2>/dev/null || true)"
    if isPositiveInteger "$DETECTED_COUNT"; then
      printf '%s\n' "$DETECTED_COUNT"
      return 0
    fi
  fi

  printf '1\n'
}

# ------------------------------------------------------------------------------
# This function checks whether a value is a positive integer.
#
# 1. "${1:-}" is the value to validate.
#
# Returns: Zero when the value is a positive integer; otherwise non-zero.
# ------------------------------------------------------------------------------
isPositiveInteger() {
  VALUE="${1:-}"

  case "$VALUE" in
    ''|*[!0-9]*)
      return 1
      ;;
  esac

  [ "$VALUE" -ge 1 ]
}

# ------------------------------------------------------------------------------
# This function converts CPU count into a bounded traversal-worker value.
#
# 1. "${1:?}" is detected CPU count as a positive integer.
#
# Returns: Recommended "SYNC_TRAVERSAL_WORKERS" value using a conservative
# Linux-host default policy.
# 
# N.B.
# The recommendation intentionally leaves headroom for NAS and host activity
# instead of mirroring total online CPU count directly.
# ------------------------------------------------------------------------------
getRecommendedTraversalWorkers() {
  CPU_COUNT="${1:?}"

  if [ "$CPU_COUNT" -le 1 ]; then
    printf '1\n'
    return 0
  fi

  if [ "$CPU_COUNT" -le 4 ]; then
    printf '2\n'
    return 0
  fi

  if [ "$CPU_COUNT" -le 6 ]; then
    printf '3\n'
    return 0
  fi

  printf '4\n'
}

CPU_COUNT="$(getCpuCount "${1:-}")"
RECOMMENDED_WORKERS="$(getRecommendedTraversalWorkers "$CPU_COUNT")"

printf 'Detected CPU count: %s\n' "$CPU_COUNT"
printf 'Recommended SYNC_TRAVERSAL_WORKERS=%s\n' "$RECOMMENDED_WORKERS"
