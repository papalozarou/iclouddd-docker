# ------------------------------------------------------------------------------
# This module encapsulates authentication and reauthentication runtime logic.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

from dateutil import parser as date_parser

from app.runtime_helpers import format_apple_id_label, notify
from app.state import AuthState, now_iso, save_auth_state
from app.telegram_bot import TelegramConfig
from app.telegram_messages import (
    build_authentication_complete_message,
    build_authentication_failed_message,
    build_authentication_required_message,
    build_reauth_reminder_message,
    build_reauthentication_required_message,
)
from app.time_utils import now_local


# ------------------------------------------------------------------------------
# This protocol describes the auth methods required from the iCloud client.
# ------------------------------------------------------------------------------
class AuthClient(Protocol):
    def complete_authentication(self, CODE: str) -> tuple[bool, str]:
        ...

    def start_authentication(self) -> tuple[bool, str]:
        ...


# ------------------------------------------------------------------------------
# This data class models one auth attempt using explicit machine-facing fields.
#
# 1. "auth_state" is the updated persisted auth state.
# 2. "is_authenticated" records final auth validity after the attempt.
# 3. "reason_code" is the stable machine-facing outcome code.
# 4. "operator_detail" is the human-readable detail returned by the client.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthAttemptResult:
    auth_state: AuthState
    is_authenticated: bool
    reason_code: str
    operator_detail: str


# ------------------------------------------------------------------------------
# This function parses an ISO timestamp with a strict epoch fallback.
#
# 1. "VALUE" is an ISO-formatted timestamp string.
#
# Returns: Offset-aware datetime; Unix epoch when parsing fails.
#
# Notes: dateutil parsing reference:
# https://dateutil.readthedocs.io/en/stable/parser.html
# ------------------------------------------------------------------------------
def parse_iso(VALUE: str) -> datetime:
    try:
        return date_parser.isoparse(VALUE)
    except (TypeError, ValueError, OverflowError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


# ------------------------------------------------------------------------------
# This function calculates remaining whole days before reauthentication.
#
# 1. "LAST_AUTH_UTC" is stored offset-aware auth timestamp.
# 2. "INTERVAL_DAYS" is the reauthentication interval in days.
#
# Returns: Remaining whole days before reauthentication should complete.
# ------------------------------------------------------------------------------
def reauth_days_left(LAST_AUTH_UTC: str, INTERVAL_DAYS: int) -> int:
    CURRENT_TIME = now_local()
    LAST_AUTH = parse_iso(LAST_AUTH_UTC).astimezone(CURRENT_TIME.tzinfo)
    ELAPSED = CURRENT_TIME - LAST_AUTH
    REMAINING = timedelta(days=INTERVAL_DAYS) - ELAPSED
    return max(0, int(REMAINING.total_seconds() // 86400))


# ------------------------------------------------------------------------------
# This data class groups runtime callbacks used by auth operations.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthRuntimeDeps:
    now_iso_fn: Callable[[], str] = now_iso
    save_auth_state_fn: Callable[[Path, AuthState], None] = save_auth_state
    notify_fn: Callable[[TelegramConfig, str], None] = notify
    log_line_fn: Callable[[Path, str, str], None] | None = None
    log_file_path: Path | None = None


# ------------------------------------------------------------------------------
# This function writes an authentication debug line when logging is available.
#
# 1. "DEPS" carries the optional logger callback and destination path.
# 2. "MESSAGE" is the already-redacted debug detail to write.
#
# Returns: None.
# ------------------------------------------------------------------------------
def log_auth_debug(DEPS: AuthRuntimeDeps, MESSAGE: str) -> None:
    if DEPS.log_line_fn is None or DEPS.log_file_path is None:
        return

    DEPS.log_line_fn(DEPS.log_file_path, "debug", MESSAGE)


# ------------------------------------------------------------------------------
# This function executes authentication and persists updated auth state.
#
# 1. "CLIENT" is iCloud client wrapper.
# 2. "AUTH_STATE" is current auth state.
# 3. "AUTH_STATE_PATH" is auth state file path.
# 4. "TELEGRAM" is Telegram integration configuration.
# 5. "USERNAME" is command prefix used by Telegram control.
# 6. "PROVIDED_CODE" is optional MFA code.
#
# Returns: "AuthAttemptResult" for the completed auth attempt.
# ------------------------------------------------------------------------------
def attempt_auth(
    CLIENT: AuthClient,
    AUTH_STATE: AuthState,
    AUTH_STATE_PATH: Path,
    TELEGRAM: TelegramConfig,
    USERNAME: str,
    APPLE_ID: str,
    PROVIDED_CODE: str,
    DEPS: AuthRuntimeDeps | None = None,
) -> AuthAttemptResult:
    RUNTIME_DEPS = DEPS or AuthRuntimeDeps()
    CODE = PROVIDED_CODE.strip()
    APPLE_ID_LABEL = format_apple_id_label(APPLE_ID)
    ATTEMPT_MODE = "complete_challenge" if CODE else "start_challenge"

    log_auth_debug(
        RUNTIME_DEPS,
        "Authentication attempt started: "
        f"mode={ATTEMPT_MODE}, "
        f"apple_id_label={APPLE_ID_LABEL}, "
        f"code_present={bool(CODE)}, "
        f"auth_pending={AUTH_STATE.auth_pending}, "
        f"reauth_pending={AUTH_STATE.reauth_pending}.",
    )

    if CODE:
        IS_SUCCESS, DETAILS = CLIENT.complete_authentication(CODE)
    else:
        IS_SUCCESS, DETAILS = CLIENT.start_authentication()

    if IS_SUCCESS:
        NEW_STATE = AuthState(
            last_auth_utc=RUNTIME_DEPS.now_iso_fn(),
            auth_pending=False,
            reauth_pending=False,
            reminder_stage="none",
        )
        RUNTIME_DEPS.save_auth_state_fn(AUTH_STATE_PATH, NEW_STATE)
        RUNTIME_DEPS.notify_fn(
            TELEGRAM,
            build_authentication_complete_message(APPLE_ID_LABEL, DETAILS),
        )
        log_auth_debug(
            RUNTIME_DEPS,
            "Authentication attempt completed: "
            "reason=authenticated, "
            "auth_pending=False, "
            "reauth_pending=False.",
        )
        return AuthAttemptResult(
            auth_state=NEW_STATE,
            is_authenticated=True,
            reason_code="authenticated",
            operator_detail=DETAILS,
        )

    if "Two-factor code is required" in DETAILS:
        NEW_STATE = replace(AUTH_STATE, auth_pending=True)
        RUNTIME_DEPS.save_auth_state_fn(AUTH_STATE_PATH, NEW_STATE)
        RUNTIME_DEPS.notify_fn(
            TELEGRAM,
            build_authentication_required_message(APPLE_ID_LABEL, USERNAME),
        )
        log_auth_debug(
            RUNTIME_DEPS,
            "Authentication attempt completed: "
            "reason=mfa_required, "
            "auth_pending=True, "
            f"reauth_pending={NEW_STATE.reauth_pending}.",
        )
        return AuthAttemptResult(
            auth_state=NEW_STATE,
            is_authenticated=False,
            reason_code="mfa_required",
            operator_detail=DETAILS,
        )

    NEW_STATE = replace(AUTH_STATE, auth_pending=True)
    RUNTIME_DEPS.save_auth_state_fn(AUTH_STATE_PATH, NEW_STATE)
    RUNTIME_DEPS.notify_fn(
        TELEGRAM,
        build_authentication_failed_message(APPLE_ID_LABEL, DETAILS),
    )
    log_auth_debug(
        RUNTIME_DEPS,
        "Authentication attempt completed: "
        "reason=auth_failed, "
        "auth_pending=True, "
        f"reauth_pending={NEW_STATE.reauth_pending}.",
    )
    return AuthAttemptResult(
        auth_state=NEW_STATE,
        is_authenticated=False,
        reason_code="auth_failed",
        operator_detail=DETAILS,
    )


# ------------------------------------------------------------------------------
# This function applies 5-day and 2-day reauthentication reminder stages.
#
# 1. "AUTH_STATE" is current auth state.
# 2. "AUTH_STATE_PATH" is persistence file path.
# 3. "TELEGRAM" is Telegram integration configuration.
# 4. "USERNAME" is command prefix.
# 5. "INTERVAL_DAYS" is reauthentication interval in days.
#
# Returns: Updated authentication state.
# ------------------------------------------------------------------------------
def process_reauth_reminders(
    AUTH_STATE: AuthState,
    AUTH_STATE_PATH: Path,
    TELEGRAM: TelegramConfig,
    USERNAME: str,
    INTERVAL_DAYS: int,
    DEPS: AuthRuntimeDeps | None = None,
    REAUTH_DAYS_LEFT_FN: Callable[[str, int], int] = reauth_days_left,
) -> AuthState:
    RUNTIME_DEPS = DEPS or AuthRuntimeDeps()
    DAYS_LEFT = REAUTH_DAYS_LEFT_FN(AUTH_STATE.last_auth_utc, INTERVAL_DAYS)
    log_auth_debug(
        RUNTIME_DEPS,
        "Reauthentication reminder check: "
        f"days_left={DAYS_LEFT}, "
        f"interval_days={INTERVAL_DAYS}, "
        f"reminder_stage={AUTH_STATE.reminder_stage}, "
        f"reauth_pending={AUTH_STATE.reauth_pending}.",
    )

    if DAYS_LEFT > 5:
        NEW_STATE = replace(AUTH_STATE, reminder_stage="none", reauth_pending=False)
        if NEW_STATE != AUTH_STATE:
            RUNTIME_DEPS.save_auth_state_fn(AUTH_STATE_PATH, NEW_STATE)
            log_auth_debug(
                RUNTIME_DEPS,
                "Reauthentication reminder state saved: "
                "reason=outside_warning_window, "
                "reminder_stage=none, "
                "reauth_pending=False.",
            )
        else:
            log_auth_debug(
                RUNTIME_DEPS,
                "Reauthentication reminder unchanged: "
                "reason=outside_warning_window.",
            )
        return NEW_STATE

    if DAYS_LEFT <= 2 and AUTH_STATE.reminder_stage != "prompt2":
        RUNTIME_DEPS.notify_fn(
            TELEGRAM,
            build_reauthentication_required_message(USERNAME),
        )
        NEW_STATE = replace(AUTH_STATE, reminder_stage="prompt2", reauth_pending=True)
        RUNTIME_DEPS.save_auth_state_fn(AUTH_STATE_PATH, NEW_STATE)
        log_auth_debug(
            RUNTIME_DEPS,
            "Reauthentication reminder state saved: "
            "reason=prompt2_due, "
            "reminder_stage=prompt2, "
            "reauth_pending=True.",
        )
        return NEW_STATE

    if DAYS_LEFT <= 5 and AUTH_STATE.reminder_stage == "none":
        RUNTIME_DEPS.notify_fn(
            TELEGRAM,
            build_reauth_reminder_message(USERNAME),
        )
        NEW_STATE = replace(AUTH_STATE, reminder_stage="alert5")
        RUNTIME_DEPS.save_auth_state_fn(AUTH_STATE_PATH, NEW_STATE)
        log_auth_debug(
            RUNTIME_DEPS,
            "Reauthentication reminder state saved: "
            "reason=alert5_due, "
            "reminder_stage=alert5, "
            f"reauth_pending={NEW_STATE.reauth_pending}.",
        )
        return NEW_STATE

    log_auth_debug(
        RUNTIME_DEPS,
        "Reauthentication reminder unchanged: reason=no_stage_transition.",
    )
    return AUTH_STATE
