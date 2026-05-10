# ------------------------------------------------------------------------------
# This module manages persisted runtime state such as manifests and
# authentication metadata.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

from app.logger import get_timestamp, log_console_line, log_line
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
# This function writes a state debug line when a worker log is available.
#
# 1. "LOG_FILE" is the optional worker log destination.
# 2. "MESSAGE" is the already-redacted diagnostic message to write.
#
# Returns: None.
# ------------------------------------------------------------------------------
def log_state_debug(LOG_FILE: Path | None, MESSAGE: str) -> None:
    if LOG_FILE is None:
        return

    log_line(LOG_FILE, "debug", MESSAGE)


# ------------------------------------------------------------------------------
# This function loads JSON content from disk with empty defaults.
#
# 1. "PATH" is the JSON file path to read.
# 2. "LOG_FILE" is the optional worker log destination.
#
# Returns: Parsed dictionary payload, or an empty dictionary when absent.
# ------------------------------------------------------------------------------
def read_json(PATH: Path, LOG_FILE: Path | None = None) -> dict[str, Any]:
    if not PATH.exists():
        log_state_debug(
            LOG_FILE,
            f"State read skipped: path={PATH.as_posix()}, reason=missing.",
        )
        return {}

    try:
        with PATH.open("r", encoding="utf-8") as HANDLE:
            PAYLOAD = json.load(HANDLE)
            log_state_debug(
                LOG_FILE,
                "State read completed: "
                f"path={PATH.as_posix()}, "
                f"payload_type={type(PAYLOAD).__name__}.",
            )
            return PAYLOAD
    except json.JSONDecodeError as ERROR:
        warn_state_issue(
            f"Corrupt JSON state ignored at {PATH}: "
            f"{type(ERROR).__name__}: {ERROR}",
        )
        log_state_debug(
            LOG_FILE,
            "State read failed: "
            f"path={PATH.as_posix()}, "
            "reason=corrupt_json.",
        )
        quarantine_corrupt_json(PATH, LOG_FILE)
        return {}
    except OSError as ERROR:
        warn_state_issue(
            f"State read failed at {PATH}: {type(ERROR).__name__}: {ERROR}",
        )
        log_state_debug(
            LOG_FILE,
            "State read failed: "
            f"path={PATH.as_posix()}, "
            f"reason={type(ERROR).__name__}.",
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
    log_console_line("error", MESSAGE)


# ------------------------------------------------------------------------------
# This function quarantines a corrupt JSON file to stop repeated parse failures.
#
# 1. "PATH" is the invalid JSON file path.
# 2. "LOG_FILE" is the optional worker log destination.
#
# Returns: None.
# ------------------------------------------------------------------------------
def quarantine_corrupt_json(PATH: Path, LOG_FILE: Path | None = None) -> None:
    QUARANTINE_PATH = PATH.with_suffix(f"{PATH.suffix}.corrupt")

    try:
        if QUARANTINE_PATH.exists():
            QUARANTINE_PATH.unlink()
            log_state_debug(
                LOG_FILE,
                "Corrupt state quarantine replaced old file: "
                f"path={QUARANTINE_PATH.as_posix()}.",
            )
    except OSError:
        log_state_debug(
            LOG_FILE,
            "Corrupt state quarantine failed: "
            f"path={QUARANTINE_PATH.as_posix()}, "
            "reason=remove_existing_failed.",
        )
        return

    try:
        PATH.replace(QUARANTINE_PATH)
        log_state_debug(
            LOG_FILE,
            "Corrupt state quarantined: "
            f"source={PATH.as_posix()}, "
            f"target={QUARANTINE_PATH.as_posix()}.",
        )
    except OSError as ERROR:
        warn_state_issue(
            f"Failed to quarantine corrupt JSON state at {PATH}: "
            f"{type(ERROR).__name__}: {ERROR}",
        )
        log_state_debug(
            LOG_FILE,
            "Corrupt state quarantine failed: "
            f"path={PATH.as_posix()}, "
            f"reason={type(ERROR).__name__}.",
        )


# ------------------------------------------------------------------------------
# This function writes JSON content atomically with a temp file.
#
# 1. "PATH" is the destination JSON file.
# 2. "PAYLOAD" is the dictionary to persist.
# 3. "LOG_FILE" is the optional worker log destination.
#
# Returns: True when the state file was written successfully.
#
# Notes: Atomic replace avoids partial writes during interruption.
# ------------------------------------------------------------------------------
def write_json(
    PATH: Path,
    PAYLOAD: dict[str, Any],
    LOG_FILE: Path | None = None,
) -> bool:
    TEMPORARY_PATH = PATH.with_suffix(PATH.suffix + ".tmp")

    try:
        with TEMPORARY_PATH.open("w", encoding="utf-8") as HANDLE:
            json.dump(PAYLOAD, HANDLE, indent=2, sort_keys=True)

        TEMPORARY_PATH.replace(PATH)
        log_state_debug(
            LOG_FILE,
            "State write completed: "
            f"path={PATH.as_posix()}, "
            f"keys={len(PAYLOAD)}.",
        )
        return True
    except OSError as ERROR:
        warn_state_issue(
            f"State write failed at {PATH}: {type(ERROR).__name__}: {ERROR}",
        )
        log_state_debug(
            LOG_FILE,
            "State write failed: "
            f"path={PATH.as_posix()}, "
            f"reason={type(ERROR).__name__}.",
        )
        cleanup_temporary_state_file(TEMPORARY_PATH, LOG_FILE)
        return False


# ------------------------------------------------------------------------------
# This function removes a temporary state file after a failed write attempt.
#
# 1. "PATH" is the temporary file path to remove.
# 2. "LOG_FILE" is the optional worker log destination.
#
# Returns: None.
# ------------------------------------------------------------------------------
def cleanup_temporary_state_file(PATH: Path, LOG_FILE: Path | None = None) -> None:
    if not PATH.exists():
        log_state_debug(
            LOG_FILE,
            f"Temporary state cleanup skipped: path={PATH.as_posix()}, reason=missing.",
        )
        return

    try:
        PATH.unlink()
        log_state_debug(
            LOG_FILE,
            f"Temporary state cleanup completed: path={PATH.as_posix()}.",
        )
    except OSError as ERROR:
        warn_state_issue(
            f"Temporary state cleanup failed at {PATH}: "
            f"{type(ERROR).__name__}: {ERROR}",
        )
        log_state_debug(
            LOG_FILE,
            "Temporary state cleanup failed: "
            f"path={PATH.as_posix()}, "
            f"reason={type(ERROR).__name__}.",
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
# 2. "LOG_FILE" is the optional worker log destination.
#
# Returns: "AuthState" with default values when fields are missing.
# ------------------------------------------------------------------------------
def load_auth_state(PATH: Path, LOG_FILE: Path | None = None) -> AuthState:
    PAYLOAD = read_json(PATH, LOG_FILE)
    DEFAULT_TIME = "1970-01-01T00:00:00+00:00"

    if not isinstance(PAYLOAD, dict):
        log_state_debug(
            LOG_FILE,
            "Auth state load used defaults: "
            f"path={PATH.as_posix()}, "
            "reason=payload_not_dict.",
        )
        return AuthState(
            last_auth_utc=DEFAULT_TIME,
            auth_pending=False,
            reauth_pending=False,
            reminder_stage="none",
        )

    STATE = AuthState(
        last_auth_utc=str(PAYLOAD.get("last_auth_utc", DEFAULT_TIME)),
        auth_pending=bool(PAYLOAD.get("auth_pending", False)),
        reauth_pending=bool(PAYLOAD.get("reauth_pending", False)),
        reminder_stage=str(PAYLOAD.get("reminder_stage", "none")),
    )
    log_state_debug(
        LOG_FILE,
        "Auth state loaded from persistence: "
        f"path={PATH.as_posix()}, "
        f"auth_pending={STATE.auth_pending}, "
        f"reauth_pending={STATE.reauth_pending}, "
        f"reminder_stage={STATE.reminder_stage}.",
    )
    return STATE


# ------------------------------------------------------------------------------
# This function persists authentication state to disk.
#
# 1. "PATH" is the JSON state file location.
# 2. "STATE" is the model to persist.
# 3. "LOG_FILE" is the optional worker log destination.
#
# Returns: True when the auth state was written successfully.
# ------------------------------------------------------------------------------
def save_auth_state(
    PATH: Path,
    STATE: AuthState,
    LOG_FILE: Path | None = None,
) -> bool:
    PAYLOAD = {
        "last_auth_utc": STATE.last_auth_utc,
        "auth_pending": STATE.auth_pending,
        "reauth_pending": STATE.reauth_pending,
        "reminder_stage": STATE.reminder_stage,
    }
    log_state_debug(
        LOG_FILE,
        "Auth state save requested: "
        f"path={PATH.as_posix()}, "
        f"auth_pending={STATE.auth_pending}, "
        f"reauth_pending={STATE.reauth_pending}, "
        f"reminder_stage={STATE.reminder_stage}.",
    )
    return write_json(PATH, PAYLOAD, LOG_FILE)


# ------------------------------------------------------------------------------
# This function loads a manifest that tracks remote file metadata by path.
#
# 1. "PATH" is the manifest file location.
# 2. "LOG_FILE" is the optional worker log destination.
#
# Returns: Mapping keyed by remote path for incremental diff checks.
# ------------------------------------------------------------------------------
def load_manifest(
    PATH: Path,
    LOG_FILE: Path | None = None,
) -> dict[str, dict[str, Any]]:
    PAYLOAD = read_json(PATH, LOG_FILE)

    if not isinstance(PAYLOAD, dict):
        log_state_debug(
            LOG_FILE,
            "Manifest load used empty payload: "
            f"path={PATH.as_posix()}, "
            "reason=payload_not_dict.",
        )
        return {}

    MANIFEST = {
        str(KEY): VALUE for KEY, VALUE in PAYLOAD.items() if isinstance(VALUE, dict)
    }
    log_state_debug(
        LOG_FILE,
        "Manifest loaded from persistence: "
        f"path={PATH.as_posix()}, "
        f"raw_entries={len(PAYLOAD)}, "
        f"valid_entries={len(MANIFEST)}.",
    )
    return MANIFEST


# ------------------------------------------------------------------------------
# This function saves the manifest in stable ordering.
#
# 1. "PATH" is the manifest file location.
# 2. "MANIFEST" is the payload to persist.
# 3. "LOG_FILE" is the optional worker log destination.
#
# Returns: True when the manifest was written successfully.
# ------------------------------------------------------------------------------
def save_manifest(
    PATH: Path,
    MANIFEST: dict[str, dict[str, Any]],
    LOG_FILE: Path | None = None,
) -> bool:
    log_state_debug(
        LOG_FILE,
        "Manifest save requested: "
        f"path={PATH.as_posix()}, "
        f"entries={len(MANIFEST)}.",
    )
    return write_json(PATH, MANIFEST, LOG_FILE)
