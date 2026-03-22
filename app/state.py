# ------------------------------------------------------------------------------
# This module manages persisted runtime state such as manifests and
# authentication metadata.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

from app.logger import get_timestamp
from app.time_utils import now_local_iso


# ------------------------------------------------------------------------------
# This data class stores authentication timestamp and pending auth flags.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthState:
    last_auth_utc: str
    auth_pending: bool
    reauth_pending: bool
    reminder_stage: str


# ------------------------------------------------------------------------------
# This function loads JSON content from disk with empty defaults.
#
# 1. "PATH" is the JSON file path to read.
#
# Returns: Parsed dictionary payload, or an empty dictionary when absent.
# ------------------------------------------------------------------------------
def read_json(PATH: Path) -> dict[str, Any]:
    if not PATH.exists():
        return {}

    try:
        with PATH.open("r", encoding="utf-8") as HANDLE:
            return json.load(HANDLE)
    except json.JSONDecodeError as ERROR:
        warn_state_issue(
            f"Corrupt JSON state ignored at {PATH}: "
            f"{type(ERROR).__name__}: {ERROR}",
        )
        quarantine_corrupt_json(PATH)
        return {}
    except OSError as ERROR:
        warn_state_issue(
            f"State read failed at {PATH}: {type(ERROR).__name__}: {ERROR}",
        )
        return {}


# ------------------------------------------------------------------------------
# This function emits a state-layer warning to worker stdout.
#
# 1. "MESSAGE" is warning content to print.
#
# Returns: None.
# ------------------------------------------------------------------------------
def warn_state_issue(MESSAGE: str) -> None:
    print(f"[{get_timestamp()}] [ERROR] {MESSAGE}", flush=True)


# ------------------------------------------------------------------------------
# This function quarantines a corrupt JSON file to stop repeated parse failures.
#
# 1. "PATH" is the invalid JSON file path.
#
# Returns: None.
# ------------------------------------------------------------------------------
def quarantine_corrupt_json(PATH: Path) -> None:
    QUARANTINE_PATH = PATH.with_suffix(f"{PATH.suffix}.corrupt")

    try:
        if QUARANTINE_PATH.exists():
            QUARANTINE_PATH.unlink()
    except OSError:
        return

    try:
        PATH.replace(QUARANTINE_PATH)
    except OSError as ERROR:
        warn_state_issue(
            f"Failed to quarantine corrupt JSON state at {PATH}: "
            f"{type(ERROR).__name__}: {ERROR}",
        )


# ------------------------------------------------------------------------------
# This function writes JSON content atomically with a temp file.
#
# 1. "PATH" is the destination JSON file.
# 2. "PAYLOAD" is the dictionary to persist.
#
# Returns: None.
#
# Notes: Atomic replace avoids partial writes during interruption.
# ------------------------------------------------------------------------------
def write_json(PATH: Path, PAYLOAD: dict[str, Any]) -> None:
    TEMPORARY_PATH = PATH.with_suffix(PATH.suffix + ".tmp")

    try:
        with TEMPORARY_PATH.open("w", encoding="utf-8") as HANDLE:
            json.dump(PAYLOAD, HANDLE, indent=2, sort_keys=True)

        TEMPORARY_PATH.replace(PATH)
    except OSError as ERROR:
        warn_state_issue(
            f"State write failed at {PATH}: {type(ERROR).__name__}: {ERROR}",
        )
        cleanup_temporary_state_file(TEMPORARY_PATH)


# ------------------------------------------------------------------------------
# This function removes a temporary state file after a failed write attempt.
#
# 1. "PATH" is the temporary file path to remove.
#
# Returns: None.
# ------------------------------------------------------------------------------
def cleanup_temporary_state_file(PATH: Path) -> None:
    if not PATH.exists():
        return

    try:
        PATH.unlink()
    except OSError as ERROR:
        warn_state_issue(
            f"Temporary state cleanup failed at {PATH}: "
            f"{type(ERROR).__name__}: {ERROR}",
        )


# ------------------------------------------------------------------------------
# This function returns a configured-timezone ISO-8601 timestamp.
#
# Returns: Offset-aware ISO-8601 timestamp string.
# ------------------------------------------------------------------------------
def now_iso() -> str:
    return now_local_iso()


# ------------------------------------------------------------------------------
# This function loads persisted authentication state with robust defaults.
#
# 1. "PATH" is the JSON state file location.
#
# Returns: "AuthState" with default values when fields are missing.
# ------------------------------------------------------------------------------
def load_auth_state(PATH: Path) -> AuthState:
    PAYLOAD = read_json(PATH)
    DEFAULT_TIME = "1970-01-01T00:00:00+00:00"

    if not isinstance(PAYLOAD, dict):
        return AuthState(
            last_auth_utc=DEFAULT_TIME,
            auth_pending=False,
            reauth_pending=False,
            reminder_stage="none",
        )

    return AuthState(
        last_auth_utc=str(PAYLOAD.get("last_auth_utc", DEFAULT_TIME)),
        auth_pending=bool(PAYLOAD.get("auth_pending", False)),
        reauth_pending=bool(PAYLOAD.get("reauth_pending", False)),
        reminder_stage=str(PAYLOAD.get("reminder_stage", "none")),
    )


# ------------------------------------------------------------------------------
# This function persists authentication state to disk.
#
# 1. "PATH" is the JSON state file location.
# 2. "STATE" is the model to persist.
#
# Returns: None.
# ------------------------------------------------------------------------------
def save_auth_state(PATH: Path, STATE: AuthState) -> None:
    PAYLOAD = {
        "last_auth_utc": STATE.last_auth_utc,
        "auth_pending": STATE.auth_pending,
        "reauth_pending": STATE.reauth_pending,
        "reminder_stage": STATE.reminder_stage,
    }
    write_json(PATH, PAYLOAD)


# ------------------------------------------------------------------------------
# This function loads a manifest that tracks remote file metadata by path.
#
# 1. "PATH" is the manifest file location.
#
# Returns: Mapping keyed by remote path for incremental diff checks.
# ------------------------------------------------------------------------------
def load_manifest(PATH: Path) -> dict[str, dict[str, Any]]:
    PAYLOAD = read_json(PATH)

    if not isinstance(PAYLOAD, dict):
        return {}

    return {
        str(KEY): VALUE for KEY, VALUE in PAYLOAD.items() if isinstance(VALUE, dict)
    }


# ------------------------------------------------------------------------------
# This function saves the manifest in stable ordering.
#
# 1. "PATH" is the manifest file location.
# 2. "MANIFEST" is the payload to persist.
#
# Returns: None.
# ------------------------------------------------------------------------------
def save_manifest(PATH: Path, MANIFEST: dict[str, dict[str, Any]]) -> None:
    write_json(PATH, MANIFEST)
