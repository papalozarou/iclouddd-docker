# ------------------------------------------------------------------------------
# This module encapsulates Telegram command polling and command handling logic.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.state import AuthState, save_auth_state
from app.telegram_bot import TelegramConfig, fetch_updates, parse_command
from app.telegram_messages import (
    build_authentication_required_message,
    build_backup_requested_message,
    build_reauthentication_required_for_apple_id_message,
)


# ------------------------------------------------------------------------------
# This function polls Telegram and returns parsed command intents.
#
# 1. "TELEGRAM" is Telegram configuration.
# 2. "USERNAME" is command prefix.
# 3. "UPDATE_OFFSET" is update offset cursor.
#
# Returns: Tuple "(commands, next_offset)" for command execution.
# ------------------------------------------------------------------------------
def process_commands(
    TELEGRAM: TelegramConfig,
    USERNAME: str,
    UPDATE_OFFSET: int | None,
    FETCH_UPDATES_FN=fetch_updates,
    PARSE_COMMAND_FN=parse_command,
) -> tuple[list[tuple[str, str]], int | None]:
    UPDATES = FETCH_UPDATES_FN(TELEGRAM, UPDATE_OFFSET)

    if not UPDATES:
        return [], UPDATE_OFFSET

    COMMANDS: list[tuple[str, str]] = []
    MAX_UPDATE = UPDATE_OFFSET or 0

    for UPDATE in UPDATES:
        EVENT = PARSE_COMMAND_FN(UPDATE, USERNAME, TELEGRAM.chat_id)
        UPDATE_ID = int(UPDATE.get("update_id", 0))
        MAX_UPDATE = max(MAX_UPDATE, UPDATE_ID + 1)

        if EVENT is None:
            continue

        COMMANDS.append((EVENT.command, EVENT.args))

    return COMMANDS, MAX_UPDATE


# ------------------------------------------------------------------------------
# This function handles a single Telegram command.
#
# 1. "COMMAND" is parsed command keyword.
# 2. "ARGS" is optional command payload.
# 3. "CONFIG" is runtime configuration.
# 4. "CLIENT" is iCloud client wrapper.
# 5. "AUTH_STATE" is current auth state.
# 6. "IS_AUTHENTICATED" tracks current auth validity.
# 7. "TELEGRAM" is Telegram integration configuration.
# 8. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 9. "ATTEMPT_AUTH_FN" executes auth flow.
# 10. "NOTIFY_FN" sends Telegram messages.
# 11. "SAVE_AUTH_STATE_FN" persists auth state.
# 12. "LOG_LINE_FN" writes worker logs.
# 13. "LOG_FILE_PATH" is the worker log path.
#
# Returns: Tuple "(auth_state, is_authenticated, backup_requested)".
# ------------------------------------------------------------------------------
def handle_command(
    COMMAND: str,
    ARGS: str,
    CONFIG: object,
    CLIENT: object,
    AUTH_STATE: AuthState,
    IS_AUTHENTICATED: bool,
    TELEGRAM: TelegramConfig,
    APPLE_ID_LABEL: str,
    ATTEMPT_AUTH_FN,
    NOTIFY_FN,
    SAVE_AUTH_STATE_FN=save_auth_state,
    LOG_LINE_FN=None,
    LOG_FILE_PATH: Path | None = None,
) -> tuple[AuthState, bool, bool]:
    if COMMAND == "backup":
        NOTIFY_FN(
            TELEGRAM,
            build_backup_requested_message(APPLE_ID_LABEL),
        )
        return AUTH_STATE, IS_AUTHENTICATED, True

    if COMMAND == "auth" and not ARGS:
        NEW_STATE = replace(AUTH_STATE, auth_pending=True)
        SAVE_AUTH_STATE_FN(CONFIG.auth_state_path, NEW_STATE)
        NOTIFY_FN(
            TELEGRAM,
            build_authentication_required_message(
                APPLE_ID_LABEL, CONFIG.container_username
            ),
        )
        return NEW_STATE, IS_AUTHENTICATED, False

    if COMMAND == "reauth" and not ARGS:
        NEW_STATE = replace(AUTH_STATE, reauth_pending=True)
        SAVE_AUTH_STATE_FN(CONFIG.auth_state_path, NEW_STATE)
        NOTIFY_FN(
            TELEGRAM,
            build_reauthentication_required_for_apple_id_message(
                APPLE_ID_LABEL, CONFIG.container_username
            ),
        )
        return NEW_STATE, IS_AUTHENTICATED, False

    NEW_STATE, NEW_AUTH, DETAILS = ATTEMPT_AUTH_FN(
        CLIENT,
        AUTH_STATE,
        CONFIG.auth_state_path,
        TELEGRAM,
        CONFIG.container_username,
        CONFIG.icloud_email,
        ARGS,
    )

    if LOG_LINE_FN is not None and LOG_FILE_PATH is not None:
        LOG_LINE_FN(LOG_FILE_PATH, "info", f"Auth command result: {DETAILS}")

    return NEW_STATE, NEW_AUTH, False
