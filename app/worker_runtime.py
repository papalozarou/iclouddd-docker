# ------------------------------------------------------------------------------
# This module encapsulates the worker runtime loop and one-shot orchestration.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Protocol

from app.auth_runtime import AuthAttemptResult
from app.command_runtime import CommandHandleResult, CommandPollBatch
from app.backup_runtime import BackupRunResult
from app.runtime_context import WorkerRuntimeContext
from app.state import AuthState
from app.telegram_bot import TelegramConfig
from app.telegram_messages import (
    build_backup_skipped_auth_incomplete_message,
    build_backup_skipped_reauth_pending_message,
    build_one_shot_waiting_for_auth_message,
)

RUN_ONCE_AUTH_WAIT_SECONDS = 900
RUN_ONCE_AUTH_POLL_SECONDS = 5


# ------------------------------------------------------------------------------
# This protocol describes the Telegram command poller used by the worker loop.
# ------------------------------------------------------------------------------
class CommandBatchPoller(Protocol):
    def __call__(
        self,
        TELEGRAM: TelegramConfig,
        USERNAME: str,
        UPDATE_OFFSET: int | None,
    ) -> CommandPollBatch:
        ...


# ------------------------------------------------------------------------------
# This data class groups runtime callbacks used by worker orchestration.
#
# N.B.
# This is the orchestration boundary for the worker loop. The runtime module
# owns loop control, one-shot waiting, and backup-trigger decisions, while the
# concrete auth, command, backup, and scheduling behaviour is injected from the
# surrounding runtime modules.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class WorkerRuntimeDeps:
    attempt_auth_fn: Callable[..., AuthAttemptResult]
    process_reauth_reminders_fn: Callable[..., AuthState]
    poll_command_batch_fn: CommandBatchPoller
    handle_command_fn: Callable[..., CommandHandleResult]
    enforce_safety_net_fn: Callable[..., bool]
    run_backup_fn: Callable[..., BackupRunResult]
    notify_fn: Callable[..., None]
    log_line_fn: Callable[..., None]
    get_next_run_epoch_fn: Callable[..., int]
    build_one_shot_waiting_for_auth_message_fn: Callable[..., str]
    build_backup_skipped_auth_incomplete_message_fn: Callable[..., str]
    build_backup_skipped_reauth_pending_message_fn: Callable[..., str]
    time_fn: Callable[[], float] = time.time
    sleep_fn: Callable[[float], None] = time.sleep


# ------------------------------------------------------------------------------
# This data class returns worker runtime exit outcome to the process entrypoint.
#
# N.B.
# This keeps the runtime module focused on orchestration decisions and leaves
# process-exit handling, container-stop notification, and heartbeat shutdown to
# the caller.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class WorkerRunResult:
    exit_code: int
    stop_status: str


# ------------------------------------------------------------------------------
# This data class tracks auth state plus live auth validity in the worker loop.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class WorkerAuthState:
    auth_state: AuthState
    is_authenticated: bool


# ------------------------------------------------------------------------------
# This data class tracks command polling cursor state for a worker run.
#
# N.B.
# Startup cutover capture and active polling share this same state object so
# update-offset ownership stays in one place inside the runtime loop.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandPollingState:
    phase: str = "startup_snapshot"
    next_update_offset: int | None = None


# ------------------------------------------------------------------------------
# This data class returns one worker-side command read plus polling state.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandBatchReadResult:
    commands: list[tuple[str, str]]
    polling_state: CommandPollingState


# ------------------------------------------------------------------------------
# This function captures the startup cutover cursor for Telegram polling.
#
# 1. "RUNTIME_CONTEXT" is shared worker runtime state.
# 2. "DEPS" groups runtime callbacks used by worker orchestration.
#
# Returns: Initialised polling state for active command polling.
#
# N.B.
# This captures the current update cursor once and discards only the updates
# already visible at that snapshot. After this point, the worker uses the
# returned cursor for all live polling, so startup no longer depends on
# message timestamps or repeated backlog-drain loops.
# ------------------------------------------------------------------------------
def capture_startup_command_polling_state(
    RUNTIME_CONTEXT: WorkerRuntimeContext,
    DEPS: WorkerRuntimeDeps,
) -> CommandPollingState:
    BATCH = DEPS.poll_command_batch_fn(
        RUNTIME_CONTEXT.TELEGRAM,
        RUNTIME_CONTEXT.CONFIG.container_username,
        None,
    )
    return CommandPollingState(
        phase="live_polling",
        next_update_offset=BATCH.next_update_offset,
    )


# ------------------------------------------------------------------------------
# This function reads the next live command batch and advances polling state.
#
# 1. "RUNTIME_CONTEXT" is shared worker runtime state.
# 2. "POLLING_STATE" is the current command polling cursor state.
# 3. "DEPS" groups runtime callbacks used by worker orchestration.
#
# Returns: "CommandBatchReadResult" for the next loop step.
# ------------------------------------------------------------------------------
def read_command_batch(
    RUNTIME_CONTEXT: WorkerRuntimeContext,
    POLLING_STATE: CommandPollingState,
    DEPS: WorkerRuntimeDeps,
) -> CommandBatchReadResult:
    BATCH = DEPS.poll_command_batch_fn(
        RUNTIME_CONTEXT.TELEGRAM,
        RUNTIME_CONTEXT.CONFIG.container_username,
        POLLING_STATE.next_update_offset,
    )
    return CommandBatchReadResult(
        commands=[(EVENT.command, EVENT.args) for EVENT in BATCH.commands],
        polling_state=CommandPollingState(
            phase="live_polling",
            next_update_offset=BATCH.next_update_offset,
        ),
    )


# ------------------------------------------------------------------------------
# This function waits for one-shot authentication commands before exit.
#
# 1. "RUNTIME_CONTEXT" is shared worker runtime state.
# 2. "CLIENT" is iCloud client wrapper.
# 3. "AUTH_RUNTIME_STATE" is current worker auth state snapshot.
# 4. "POLLING_STATE" is the captured live polling cursor state.
# 5. "DEPS" groups runtime callbacks used by worker orchestration.
#
# Returns: "WorkerAuthState" after one-shot auth waiting completes.
# ------------------------------------------------------------------------------
def wait_for_one_shot_auth(
    RUNTIME_CONTEXT: WorkerRuntimeContext,
    CLIENT: Any,
    AUTH_RUNTIME_STATE: WorkerAuthState,
    POLLING_STATE: CommandPollingState,
    DEPS: WorkerRuntimeDeps,
) -> WorkerAuthState:
    START_EPOCH = int(DEPS.time_fn())

    while True:
        if (
            AUTH_RUNTIME_STATE.is_authenticated
            and not AUTH_RUNTIME_STATE.auth_state.reauth_pending
        ):
            return AUTH_RUNTIME_STATE

        NOW_EPOCH = int(DEPS.time_fn())
        ELAPSED_SECONDS = NOW_EPOCH - START_EPOCH

        if ELAPSED_SECONDS >= RUN_ONCE_AUTH_WAIT_SECONDS:
            return AUTH_RUNTIME_STATE

        READ_RESULT = read_command_batch(
            RUNTIME_CONTEXT,
            POLLING_STATE,
            DEPS,
        )
        POLLING_STATE = READ_RESULT.polling_state

        for COMMAND, ARGS in READ_RESULT.commands:
            HANDLE_RESULT = DEPS.handle_command_fn(
                COMMAND,
                ARGS,
                RUNTIME_CONTEXT.CONFIG,
                CLIENT,
                AUTH_RUNTIME_STATE.auth_state,
                AUTH_RUNTIME_STATE.is_authenticated,
                RUNTIME_CONTEXT.TELEGRAM,
            )
            AUTH_RUNTIME_STATE = WorkerAuthState(
                auth_state=HANDLE_RESULT.auth_state,
                is_authenticated=HANDLE_RESULT.is_authenticated,
            )
            if (
                AUTH_RUNTIME_STATE.is_authenticated
                and not AUTH_RUNTIME_STATE.auth_state.reauth_pending
            ):
                return AUTH_RUNTIME_STATE

        DEPS.sleep_fn(RUN_ONCE_AUTH_POLL_SECONDS)


# ------------------------------------------------------------------------------
# This function logs startup authentication status after the initial attempt.
#
# 1. "RUNTIME_CONTEXT" is shared worker runtime state.
# 2. "AUTH_RESULT" is startup auth attempt outcome.
# 3. "DEPS" groups runtime callbacks used by worker orchestration.
#
# Returns: None.
# ------------------------------------------------------------------------------
def log_startup_auth_state(
    RUNTIME_CONTEXT: WorkerRuntimeContext,
    AUTH_RESULT: AuthAttemptResult,
    DEPS: WorkerRuntimeDeps,
) -> None:
    DEPS.log_line_fn(RUNTIME_CONTEXT.LOG_FILE, "info", AUTH_RESULT.operator_detail)
    DEPS.log_line_fn(
        RUNTIME_CONTEXT.LOG_FILE,
        "debug",
        "Auth state after startup attempt: "
        f"is_authenticated={AUTH_RESULT.is_authenticated}, "
        f"auth_pending={AUTH_RESULT.auth_state.auth_pending}, "
        f"reauth_pending={AUTH_RESULT.auth_state.reauth_pending}, "
        f"reason_code={AUTH_RESULT.reason_code}",
    )


# ------------------------------------------------------------------------------
# This function executes the one-shot worker path after startup auth.
#
# 1. "RUNTIME_CONTEXT" is shared worker runtime state.
# 2. "CLIENT" is iCloud client wrapper.
# 3. "AUTH_RUNTIME_STATE" is current worker auth state snapshot.
# 4. "POLLING_STATE" is the captured live polling cursor state.
# 5. "DEPS" groups runtime callbacks used by worker orchestration.
#
# Returns: Worker exit result for one-shot processing.
# ------------------------------------------------------------------------------
def run_one_shot_worker(
    RUNTIME_CONTEXT: WorkerRuntimeContext,
    CLIENT: Any,
    AUTH_RUNTIME_STATE: WorkerAuthState,
    POLLING_STATE: CommandPollingState,
    DEPS: WorkerRuntimeDeps,
) -> WorkerRunResult:
    if (
        not AUTH_RUNTIME_STATE.is_authenticated
        or AUTH_RUNTIME_STATE.auth_state.reauth_pending
    ):
        DEPS.notify_fn(
            RUNTIME_CONTEXT.TELEGRAM,
            DEPS.build_one_shot_waiting_for_auth_message_fn(
                RUNTIME_CONTEXT.APPLE_ID_LABEL,
                max(1, RUN_ONCE_AUTH_WAIT_SECONDS // 60),
            ),
        )
        AUTH_RUNTIME_STATE = wait_for_one_shot_auth(
            RUNTIME_CONTEXT,
            CLIENT,
            AUTH_RUNTIME_STATE,
            POLLING_STATE,
            DEPS,
        )

    if not AUTH_RUNTIME_STATE.is_authenticated:
        DEPS.notify_fn(
            RUNTIME_CONTEXT.TELEGRAM,
            DEPS.build_backup_skipped_auth_incomplete_message_fn(
                RUNTIME_CONTEXT.APPLE_ID_LABEL
            ),
        )
        return WorkerRunResult(
            exit_code=2,
            stop_status="One-shot backup skipped due to incomplete authentication.",
        )

    if AUTH_RUNTIME_STATE.auth_state.reauth_pending:
        DEPS.notify_fn(
            RUNTIME_CONTEXT.TELEGRAM,
            DEPS.build_backup_skipped_reauth_pending_message_fn(
                RUNTIME_CONTEXT.APPLE_ID_LABEL
            ),
        )
        return WorkerRunResult(
            exit_code=3,
            stop_status="One-shot backup skipped due to pending reauthentication.",
        )

    if not DEPS.enforce_safety_net_fn(
        RUNTIME_CONTEXT.CONFIG,
        RUNTIME_CONTEXT.TELEGRAM,
        RUNTIME_CONTEXT.LOG_FILE,
    ):
        return WorkerRunResult(
            exit_code=4,
            stop_status="One-shot backup blocked by safety net.",
        )

    DEPS.run_backup_fn(
        CLIENT,
        RUNTIME_CONTEXT.CONFIG,
        RUNTIME_CONTEXT.TELEGRAM,
        RUNTIME_CONTEXT.LOG_FILE,
        "one-shot",
    )
    return WorkerRunResult(
        exit_code=0,
        stop_status="Run completed and container exited.",
    )


# ------------------------------------------------------------------------------
# This function executes the scheduled or manual worker loop indefinitely.
#
# 1. "RUNTIME_CONTEXT" is shared worker runtime state.
# 2. "CLIENT" is iCloud client wrapper.
# 3. "AUTH_RUNTIME_STATE" is current worker auth state snapshot.
# 4. "POLLING_STATE" is the captured live polling cursor state.
# 5. "DEPS" groups runtime callbacks used by worker orchestration.
#
# Returns: This function does not return during normal operation.
# ------------------------------------------------------------------------------
def run_scheduled_worker_loop(
    RUNTIME_CONTEXT: WorkerRuntimeContext,
    CLIENT: Any,
    AUTH_RUNTIME_STATE: WorkerAuthState,
    POLLING_STATE: CommandPollingState,
    DEPS: WorkerRuntimeDeps,
) -> None:
    BACKUP_REQUESTED = False
    INITIAL_EPOCH = int(DEPS.time_fn())

    if RUNTIME_CONTEXT.CONFIG.schedule_mode == "interval":
        NEXT_RUN_EPOCH = INITIAL_EPOCH
    else:
        NEXT_RUN_EPOCH = DEPS.get_next_run_epoch_fn(
            RUNTIME_CONTEXT.CONFIG,
            INITIAL_EPOCH,
        )

    while True:
        AUTH_RUNTIME_STATE = WorkerAuthState(
            auth_state=DEPS.process_reauth_reminders_fn(
                AUTH_RUNTIME_STATE.auth_state,
                RUNTIME_CONTEXT.CONFIG.auth_state_path,
                RUNTIME_CONTEXT.TELEGRAM,
                RUNTIME_CONTEXT.CONFIG.container_username,
                RUNTIME_CONTEXT.CONFIG.reauth_interval_days,
            ),
            is_authenticated=AUTH_RUNTIME_STATE.is_authenticated,
        )
        READ_RESULT = read_command_batch(
            RUNTIME_CONTEXT,
            POLLING_STATE,
            DEPS,
        )
        POLLING_STATE = READ_RESULT.polling_state

        for COMMAND, ARGS in READ_RESULT.commands:
            HANDLE_RESULT = DEPS.handle_command_fn(
                COMMAND,
                ARGS,
                RUNTIME_CONTEXT.CONFIG,
                CLIENT,
                AUTH_RUNTIME_STATE.auth_state,
                AUTH_RUNTIME_STATE.is_authenticated,
                RUNTIME_CONTEXT.TELEGRAM,
            )
            AUTH_RUNTIME_STATE = WorkerAuthState(
                auth_state=HANDLE_RESULT.auth_state,
                is_authenticated=HANDLE_RESULT.is_authenticated,
            )
            BACKUP_REQUESTED = BACKUP_REQUESTED or HANDLE_RESULT.backup_requested

        NOW_EPOCH = int(DEPS.time_fn())
        SCHEDULE_DUE = NOW_EPOCH >= NEXT_RUN_EPOCH

        if not SCHEDULE_DUE and not BACKUP_REQUESTED:
            DEPS.sleep_fn(5)
            continue

        NEXT_RUN_EPOCH = DEPS.get_next_run_epoch_fn(
            RUNTIME_CONTEXT.CONFIG,
            NOW_EPOCH,
        )

        if not AUTH_RUNTIME_STATE.is_authenticated:
            DEPS.notify_fn(
                RUNTIME_CONTEXT.TELEGRAM,
                DEPS.build_backup_skipped_auth_incomplete_message_fn(
                    RUNTIME_CONTEXT.APPLE_ID_LABEL
                ),
            )
            BACKUP_REQUESTED = False
            DEPS.sleep_fn(5)
            continue

        if AUTH_RUNTIME_STATE.auth_state.reauth_pending:
            DEPS.notify_fn(
                RUNTIME_CONTEXT.TELEGRAM,
                DEPS.build_backup_skipped_reauth_pending_message_fn(
                    RUNTIME_CONTEXT.APPLE_ID_LABEL
                ),
            )
            BACKUP_REQUESTED = False
            DEPS.sleep_fn(5)
            continue

        if not DEPS.enforce_safety_net_fn(
            RUNTIME_CONTEXT.CONFIG,
            RUNTIME_CONTEXT.TELEGRAM,
            RUNTIME_CONTEXT.LOG_FILE,
        ):
            BACKUP_REQUESTED = False
            DEPS.sleep_fn(30)
            continue

        BACKUP_TRIGGER = "manual" if BACKUP_REQUESTED else "scheduled"
        DEPS.run_backup_fn(
            CLIENT,
            RUNTIME_CONTEXT.CONFIG,
            RUNTIME_CONTEXT.TELEGRAM,
            RUNTIME_CONTEXT.LOG_FILE,
            BACKUP_TRIGGER,
        )
        BACKUP_REQUESTED = False
        DEPS.sleep_fn(5)


# ------------------------------------------------------------------------------
# This function executes the worker runtime after bootstrap has completed.
#
# 1. "RUNTIME_CONTEXT" is shared worker runtime state.
# 2. "CLIENT" is iCloud client wrapper.
# 3. "AUTH_STATE" is persisted auth state loaded during startup.
# 4. "DEPS" groups runtime callbacks used by worker orchestration.
#
# Returns: Worker exit result for the calling process entrypoint.
# ------------------------------------------------------------------------------
def run_worker_runtime(
    RUNTIME_CONTEXT: WorkerRuntimeContext,
    CLIENT: Any,
    AUTH_STATE: AuthState,
    DEPS: WorkerRuntimeDeps,
) -> WorkerRunResult:
    POLLING_STATE = capture_startup_command_polling_state(
        RUNTIME_CONTEXT,
        DEPS,
    )
    AUTH_RESULT = DEPS.attempt_auth_fn(
        CLIENT,
        AUTH_STATE,
        RUNTIME_CONTEXT.CONFIG.auth_state_path,
        RUNTIME_CONTEXT.TELEGRAM,
        RUNTIME_CONTEXT.CONFIG.container_username,
        RUNTIME_CONTEXT.CONFIG.icloud_email,
        "",
    )
    log_startup_auth_state(
        RUNTIME_CONTEXT,
        AUTH_RESULT,
        DEPS,
    )
    AUTH_RUNTIME_STATE = WorkerAuthState(
        auth_state=AUTH_RESULT.auth_state,
        is_authenticated=AUTH_RESULT.is_authenticated,
    )

    if RUNTIME_CONTEXT.CONFIG.run_once:
        return run_one_shot_worker(
            RUNTIME_CONTEXT,
            CLIENT,
            AUTH_RUNTIME_STATE,
            POLLING_STATE,
            DEPS,
        )

    run_scheduled_worker_loop(
        RUNTIME_CONTEXT,
        CLIENT,
        AUTH_RUNTIME_STATE,
        POLLING_STATE,
        DEPS,
    )
    return WorkerRunResult(
        exit_code=0,
        stop_status="Worker process exited.",
    )
