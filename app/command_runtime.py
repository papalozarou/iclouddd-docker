# ------------------------------------------------------------------------------
# This module encapsulates Telegram command polling and command handling logic.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Protocol

from app.auth_runtime import AuthAttemptResult
from app.state import AuthState, save_auth_state
from app.telegram_bot import CommandEvent, TelegramConfig, fetch_updates, parse_command
from app.telegram_messages import (
    build_backup_requested_message,
)


# ------------------------------------------------------------------------------
# This protocol describes the config values required for command handling.
# ------------------------------------------------------------------------------
class CommandConfig(Protocol):
    auth_state_path: Path
    container_username: str
    icloud_email: str


# ------------------------------------------------------------------------------
# This protocol is a marker for the command handler's iCloud client argument.
# ------------------------------------------------------------------------------
class CommandClient(Protocol):
    ...


# ------------------------------------------------------------------------------
# This data class groups Telegram polling callbacks used by command polling.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandPollingDeps:
    fetch_updates_fn: Callable = fetch_updates
    parse_command_fn: Callable = parse_command


# ------------------------------------------------------------------------------
# This constant asks Telegram to discard the visible command backlog and return
# only the latest currently queued update for cutover cursor capture.
# ------------------------------------------------------------------------------
STARTUP_CUTOVER_OFFSET = -1


# ------------------------------------------------------------------------------
# This data class returns one polled Telegram update batch plus cursor state.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandPollBatch:
    commands: list[CommandEvent]
    next_update_offset: int | None


# ------------------------------------------------------------------------------
# This data class models one handled command using explicit result fields.
#
# 1. "auth_state" is the updated auth state after command handling.
# 2. "is_authenticated" records final auth validity.
# 3. "backup_requested" records whether this command requested a backup.
# 4. "reason_code" is the stable machine-facing command outcome code.
# 5. "operator_detail" is optional human-readable detail for logs.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandHandleResult:
    auth_state: AuthState
    is_authenticated: bool
    backup_requested: bool
    reason_code: str
    operator_detail: str = ""


# ------------------------------------------------------------------------------
# This data class groups runtime callbacks used by command handling.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandRuntimeDeps:
    attempt_auth_fn: Callable[..., AuthAttemptResult]
    notify_fn: Callable[[TelegramConfig, str], None]
    save_auth_state_fn: Callable[[Path, AuthState], None] = save_auth_state
    log_line_fn: Callable | None = None
    log_file_path: Path | None = None


# ------------------------------------------------------------------------------
# This function polls Telegram and returns parsed command intents.
#
# 1. "TELEGRAM" is Telegram configuration.
# 2. "USERNAME" is command prefix.
# 3. "UPDATE_OFFSET" is update offset cursor.
#
# Returns: Tuple "(commands, next_offset)" for command execution.
# ------------------------------------------------------------------------------
def poll_command_batch(
    TELEGRAM: TelegramConfig,
    USERNAME: str,
    UPDATE_OFFSET: int | None,
    DEPS: CommandPollingDeps | None = None,
) -> CommandPollBatch:
    RUNTIME_DEPS = DEPS or CommandPollingDeps()
    UPDATES = RUNTIME_DEPS.fetch_updates_fn(TELEGRAM, UPDATE_OFFSET)

    if not UPDATES:
        NEXT_UPDATE_OFFSET = None if UPDATE_OFFSET is not None and UPDATE_OFFSET < 0 else UPDATE_OFFSET
        return CommandPollBatch([], NEXT_UPDATE_OFFSET)

    COMMANDS: list[CommandEvent] = []
    MAX_UPDATE = UPDATE_OFFSET or 0

    for UPDATE in UPDATES:
        EVENT = RUNTIME_DEPS.parse_command_fn(UPDATE, USERNAME, TELEGRAM.chat_id)
        UPDATE_ID = int(UPDATE.get("update_id", 0))
        MAX_UPDATE = max(MAX_UPDATE, UPDATE_ID + 1)

        if EVENT is None:
            continue

        COMMANDS.append(EVENT)

    return CommandPollBatch(COMMANDS, MAX_UPDATE)


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
    DEPS: CommandPollingDeps | None = None,
) -> tuple[list[tuple[str, str]], int | None]:
    BATCH = poll_command_batch(
        TELEGRAM,
        USERNAME,
        UPDATE_OFFSET,
        DEPS,
    )
    return [(EVENT.command, EVENT.args) for EVENT in BATCH.commands], BATCH.next_update_offset


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
# 9. "DEPS" groups runtime callbacks used by command handling.
#
# Returns: "CommandHandleResult" for the handled command.
# ------------------------------------------------------------------------------
def handle_command(
    COMMAND: str,
    ARGS: str,
    CONFIG: CommandConfig,
    CLIENT: CommandClient,
    AUTH_STATE: AuthState,
    IS_AUTHENTICATED: bool,
    TELEGRAM: TelegramConfig,
    APPLE_ID_LABEL: str,
    DEPS: CommandRuntimeDeps,
) -> CommandHandleResult:
    if COMMAND == "backup":
        DEPS.notify_fn(
            TELEGRAM,
            build_backup_requested_message(APPLE_ID_LABEL),
        )
        return CommandHandleResult(
            auth_state=AUTH_STATE,
            is_authenticated=IS_AUTHENTICATED,
            backup_requested=True,
            reason_code="backup_requested",
        )

    if COMMAND == "auth" and not ARGS:
        AUTH_RESULT = DEPS.attempt_auth_fn(
            CLIENT,
            AUTH_STATE,
            CONFIG.auth_state_path,
            TELEGRAM,
            CONFIG.container_username,
            CONFIG.icloud_email,
            "",
        )

        if DEPS.log_line_fn is not None and DEPS.log_file_path is not None:
            DEPS.log_line_fn(
                DEPS.log_file_path,
                "info",
                f"Auth command result: {AUTH_RESULT.operator_detail}",
            )

        return CommandHandleResult(
            auth_state=AUTH_RESULT.auth_state,
            is_authenticated=AUTH_RESULT.is_authenticated,
            backup_requested=False,
            reason_code=AUTH_RESULT.reason_code,
            operator_detail=AUTH_RESULT.operator_detail,
        )

    if COMMAND == "reauth" and not ARGS:
        REAUTH_STATE = replace(AUTH_STATE, reauth_pending=True)
        AUTH_RESULT = DEPS.attempt_auth_fn(
            CLIENT,
            REAUTH_STATE,
            CONFIG.auth_state_path,
            TELEGRAM,
            CONFIG.container_username,
            CONFIG.icloud_email,
            "",
        )

        if DEPS.log_line_fn is not None and DEPS.log_file_path is not None:
            DEPS.log_line_fn(
                DEPS.log_file_path,
                "info",
                f"Auth command result: {AUTH_RESULT.operator_detail}",
            )

        return CommandHandleResult(
            auth_state=AUTH_RESULT.auth_state,
            is_authenticated=AUTH_RESULT.is_authenticated,
            backup_requested=False,
            reason_code=AUTH_RESULT.reason_code,
            operator_detail=AUTH_RESULT.operator_detail,
        )

    AUTH_RESULT = DEPS.attempt_auth_fn(
        CLIENT,
        AUTH_STATE,
        CONFIG.auth_state_path,
        TELEGRAM,
        CONFIG.container_username,
        CONFIG.icloud_email,
        ARGS,
    )

    if DEPS.log_line_fn is not None and DEPS.log_file_path is not None:
        DEPS.log_line_fn(
            DEPS.log_file_path,
            "info",
            f"Auth command result: {AUTH_RESULT.operator_detail}",
        )

    return CommandHandleResult(
        auth_state=AUTH_RESULT.auth_state,
        is_authenticated=AUTH_RESULT.is_authenticated,
        backup_requested=False,
        reason_code=AUTH_RESULT.reason_code,
        operator_detail=AUTH_RESULT.operator_detail,
    )
