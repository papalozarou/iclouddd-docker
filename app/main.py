# ------------------------------------------------------------------------------
# This module runs the backup worker loop and coordinates auth and sync.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import threading

import app.auth_runtime as auth_runtime
import app.backup_runtime as backup_runtime
import app.command_runtime as command_runtime
import app.worker_runtime as worker_runtime
from app.config import AppConfig, load_config
from app.config_validation import validate_config
from app.credential_store import configure_keyring, load_credentials, save_credentials
from app.icloud_client import ICloudDriveClient
from app.logger import log_line
from app.runtime_helpers import format_apple_id_label, notify
from app.scheduler import (
    format_schedule_line,
    get_next_run_epoch,
)
from app.runtime_context import WorkerRuntimeContext
from app.state import AuthState, load_auth_state, load_manifest, now_iso, save_auth_state, save_manifest
from app.runtime_constants import HEARTBEAT_TOUCH_INTERVAL_SECONDS
from app.syncer import perform_incremental_sync, run_first_time_safety_net
from app.telegram_bot import TelegramConfig, fetch_updates, parse_command
from app.telegram_messages import (
    build_container_started_message,
    build_container_stopped_message,
    build_safety_net_blocked_message,
)
from app.time_utils import now_local


# ------------------------------------------------------------------------------
# This data class stores mutable heartbeat telemetry for runtime liveness.
#
# 1. "first_attempt_epoch" stores the first attempted touch epoch.
# 2. "last_success_epoch" stores the last successful touch epoch.
# 3. "last_attempt_epoch" stores the last attempted touch epoch.
# 4. "last_failure_detail" stores the last write failure detail.
# 5. "loop_exit_reason" stores why the heartbeat thread stopped.
# ------------------------------------------------------------------------------
@dataclass
class HeartbeatTelemetry:
    first_attempt_epoch: float = 0.0
    last_success_epoch: float = 0.0
    last_attempt_epoch: float = 0.0
    last_failure_detail: str = ""
    loop_exit_reason: str = ""


# ------------------------------------------------------------------------------
# This data class owns a running heartbeat updater thread.
#
# 1. "stop_event" is the signal watched by the updater loop.
# 2. "thread" is the background writer that touches the heartbeat file.
# 3. "telemetry" stores live heartbeat status for runtime checks.
# 4. "max_age_seconds" is the shared worker and healthcheck liveness budget.
#
# N.B.
# The worker must join this thread during shutdown. Setting the stop event alone
# leaves a small race where tests or container cleanup can remove the logs
# directory while the heartbeat writer is still finishing its final iteration.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class HeartbeatUpdater:
    stop_event: threading.Event
    thread: threading.Thread
    telemetry: HeartbeatTelemetry
    max_age_seconds: int

    # --------------------------------------------------------------------------
    # This method stops the heartbeat loop and waits for the writer to exit.
    #
    # Returns: None.
    # --------------------------------------------------------------------------
    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join()

    # --------------------------------------------------------------------------
    # This method returns heartbeat liveness failure detail when unhealthy.
    #
    # 1. "NOW_EPOCH" is current wall-clock epoch seconds.
    #
    # Returns: Redacted failure detail, otherwise None.
    # --------------------------------------------------------------------------
    def get_liveness_failure(self, NOW_EPOCH: float) -> str | None:
        if not self.thread.is_alive():
            if self.loop_stopped_due_to_shutdown():
                return None

            if self.telemetry.loop_exit_reason:
                return (
                    "heartbeat_thread_stopped: "
                    f"reason={self.telemetry.loop_exit_reason}."
                )

            return "heartbeat_thread_stopped: reason=thread_not_alive."

        LAST_SUCCESS_EPOCH = self.telemetry.last_success_epoch
        if LAST_SUCCESS_EPOCH <= 0:
            if self.is_startup_failure_ready(NOW_EPOCH):
                return (
                    "heartbeat_startup_failed: "
                    f"age_seconds={self.first_failure_age_seconds(NOW_EPOCH)}, "
                    f"detail={self.telemetry.last_failure_detail}."
                )

            return None

        STALE_SECONDS = int(max(NOW_EPOCH - LAST_SUCCESS_EPOCH, 0))
        if STALE_SECONDS <= self.max_age_seconds:
            return None

        FAILURE_DETAIL = self.telemetry.last_failure_detail or "heartbeat_not_advanced"
        return (
            "heartbeat_stale: "
            f"age_seconds={STALE_SECONDS}, "
            f"detail={FAILURE_DETAIL}."
        )

    # --------------------------------------------------------------------------
    # This method reports whether the heartbeat loop stopped on shutdown.
    #
    # Returns: True when the stop reason is the expected shutdown path.
    # --------------------------------------------------------------------------
    def loop_stopped_due_to_shutdown(self) -> bool:
        return self.telemetry.loop_exit_reason == "stop_requested"

    # --------------------------------------------------------------------------
    # This method reports whether failed startup heartbeats have aged out.
    #
    # 1. "NOW_EPOCH" is current wall-clock epoch seconds.
    #
    # Returns: True when startup failures must now trip runtime liveness.
    # --------------------------------------------------------------------------
    def is_startup_failure_ready(self, NOW_EPOCH: float) -> bool:
        if not self.telemetry.last_failure_detail:
            return False

        FIRST_ATTEMPT_EPOCH = self.telemetry.first_attempt_epoch
        if FIRST_ATTEMPT_EPOCH <= 0:
            return False

        return self.first_failure_age_seconds(NOW_EPOCH) > self.max_age_seconds

    # --------------------------------------------------------------------------
    # This method returns startup failure age from the first heartbeat attempt.
    #
    # 1. "NOW_EPOCH" is current wall-clock epoch seconds.
    #
    # Returns: Non-negative whole seconds since first heartbeat attempt.
    # --------------------------------------------------------------------------
    def first_failure_age_seconds(self, NOW_EPOCH: float) -> int:
        return int(max(NOW_EPOCH - self.telemetry.first_attempt_epoch, 0))


# ------------------------------------------------------------------------------
# This function updates the healthcheck heartbeat file timestamp.
#
# 1. "PATH" is the heartbeat file path.
#
# Returns: Tuple of success flag and redacted failure detail.
# ------------------------------------------------------------------------------
def update_heartbeat(PATH: Path) -> tuple[bool, str]:
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.touch()
    except OSError as ERROR:
        return False, f"{type(ERROR).__name__}: {ERROR}"

    return True, ""


# ------------------------------------------------------------------------------
# This function starts a daemon heartbeat updater thread.
#
# 1. "PATH" is the heartbeat file path.
# 2. "LOG_FILE" is the worker log destination used for failure lines.
# 3. "MAX_AGE_SECONDS" is the shared worker and healthcheck liveness budget.
#
# Returns: Heartbeat updater controller used for clean process shutdown.
# ------------------------------------------------------------------------------
def start_heartbeat_updater(
    PATH: Path,
    LOG_FILE: Path,
    MAX_AGE_SECONDS: int,
) -> HeartbeatUpdater:
    STOP_EVENT = threading.Event()
    TELEMETRY = HeartbeatTelemetry()

    # --------------------------------------------------------------------------
    # This function writes heartbeat timestamps until shutdown is requested.
    #
    # Returns: None.
    # --------------------------------------------------------------------------
    def run_heartbeat_loop() -> None:
        try:
            while True:
                TELEMETRY.last_attempt_epoch = worker_runtime.time.time()
                if TELEMETRY.first_attempt_epoch <= 0:
                    TELEMETRY.first_attempt_epoch = TELEMETRY.last_attempt_epoch
                IS_SUCCESS, FAILURE_DETAIL = update_heartbeat(PATH)

                if IS_SUCCESS:
                    TELEMETRY.last_success_epoch = TELEMETRY.last_attempt_epoch
                    TELEMETRY.last_failure_detail = ""
                else:
                    TELEMETRY.last_failure_detail = FAILURE_DETAIL
                    log_line(
                        LOG_FILE,
                        "error",
                        "Heartbeat update failed: "
                        f"path={PATH.as_posix()}, "
                        f"detail={FAILURE_DETAIL}.",
                    )

                if STOP_EVENT.wait(HEARTBEAT_TOUCH_INTERVAL_SECONDS):
                    TELEMETRY.loop_exit_reason = "stop_requested"
                    return
        except Exception as ERROR:
            TELEMETRY.loop_exit_reason = f"{type(ERROR).__name__}: {ERROR}"
            log_line(
                LOG_FILE,
                "error",
                "Heartbeat updater crashed: "
                f"path={PATH.as_posix()}, "
                f"detail={TELEMETRY.loop_exit_reason}.",
            )

    THREAD = threading.Thread(target=run_heartbeat_loop, daemon=True)
    THREAD.start()
    return HeartbeatUpdater(
        stop_event=STOP_EVENT,
        thread=THREAD,
        telemetry=TELEMETRY,
        max_age_seconds=MAX_AGE_SECONDS,
    )


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
    CLIENT: ICloudDriveClient,
    AUTH_STATE: AuthState,
    AUTH_STATE_PATH: Path,
    TELEGRAM: TelegramConfig,
    USERNAME: str,
    APPLE_ID: str,
    PROVIDED_CODE: str,
) -> auth_runtime.AuthAttemptResult:
    LOG_FILE = getattr(CLIENT.config, "worker_log_path", None)
    AUTH_RESULT = auth_runtime.attempt_auth(
        CLIENT,
        AUTH_STATE,
        AUTH_STATE_PATH,
        TELEGRAM,
        USERNAME,
        APPLE_ID,
        PROVIDED_CODE,
        DEPS=auth_runtime.AuthRuntimeDeps(
            now_iso_fn=now_iso,
            save_auth_state_fn=(
                lambda PATH, STATE: save_auth_state(PATH, STATE, LOG_FILE)
            ),
            notify_fn=notify,
            log_line_fn=log_line,
            log_file_path=LOG_FILE,
        ),
    )
    if AUTH_RESULT.is_authenticated:
        save_credentials(
            CLIENT.config.keychain_service_name,
            USERNAME,
            CLIENT.config.icloud_email,
            CLIENT.config.icloud_password,
        )
    return AUTH_RESULT


# ------------------------------------------------------------------------------
# This function applies 5-day and 2-day reauthentication reminder stages.
#
# 1. "AUTH_STATE" is current auth state.
# 2. "AUTH_STATE_PATH" is persistence file path.
# 3. "TELEGRAM" is Telegram integration configuration.
# 4. "USERNAME" is Telegram command prefix.
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
    LOG_FILE: Path | None = None,
) -> AuthState:
    return auth_runtime.process_reauth_reminders(
        AUTH_STATE,
        AUTH_STATE_PATH,
        TELEGRAM,
        USERNAME,
        INTERVAL_DAYS,
        DEPS=auth_runtime.AuthRuntimeDeps(
            save_auth_state_fn=(
                lambda PATH, STATE: save_auth_state(PATH, STATE, LOG_FILE)
            ),
            notify_fn=notify,
            log_line_fn=log_line,
            log_file_path=LOG_FILE,
        ),
        REAUTH_DAYS_LEFT_FN=auth_runtime.reauth_days_left,
    )


# ------------------------------------------------------------------------------
# This function enforces first-run safety checks before backups are allowed.
#
# 1. "CONFIG" is runtime configuration.
# 2. "TELEGRAM" is Telegram integration configuration.
# 3. "LOG_FILE" is worker log path.
#
# Returns: True when backup can proceed; otherwise False.
# ------------------------------------------------------------------------------
def enforce_safety_net(CONFIG: AppConfig, TELEGRAM: TelegramConfig, LOG_FILE: Path) -> bool:
    DONE_MARKER = CONFIG.safety_net_done_path
    BLOCKED_MARKER = CONFIG.safety_net_blocked_path

    log_line(
        LOG_FILE,
        "debug",
        "Safety net check started: "
        f"done_marker={DONE_MARKER.as_posix()}, "
        f"blocked_marker={BLOCKED_MARKER.as_posix()}, "
        f"sample_size={CONFIG.safety_net_sample_size}.",
    )

    if DONE_MARKER.exists():
        log_line(
            LOG_FILE,
            "debug",
            "Safety net check skipped: reason=done_marker_exists.",
        )
        return True

    RESULT = run_first_time_safety_net(CONFIG.output_dir, CONFIG.safety_net_sample_size)
    log_line(
        LOG_FILE,
        "debug",
        "Safety net scan result: "
        f"should_block={RESULT.should_block}, "
        f"expected_uid={RESULT.expected_uid}, "
        f"expected_gid={RESULT.expected_gid}, "
        f"mismatched_samples={len(RESULT.mismatched_samples)}.",
    )

    if not RESULT.should_block and BLOCKED_MARKER.exists():
        BLOCKED_MARKER.unlink()
        log_line(
            LOG_FILE,
            "debug",
            "Safety net stale blocked marker removed.",
        )

    if not RESULT.should_block:
        DONE_MARKER.write_text("ok\n", encoding="utf-8")
        log_line(
            LOG_FILE,
            "debug",
            f"Safety net done marker written: path={DONE_MARKER.as_posix()}.",
        )
        log_line(LOG_FILE, "info", "First-run safety net passed.")
        return True

    if BLOCKED_MARKER.exists():
        log_line(
            LOG_FILE,
            "debug",
            "Safety net remains blocked: reason=blocked_marker_exists.",
        )
        return False

    MISMATCH_TEXT = "\n".join(RESULT.mismatched_samples)
    log_line(LOG_FILE, "error", "Safety net blocked backup due to permissions.")
    log_line(LOG_FILE, "error", MISMATCH_TEXT)
    APPLE_ID_LABEL = format_apple_id_label(CONFIG.icloud_email)
    SAMPLE_TEXT = ", ".join(RESULT.mismatched_samples[:2]) or "<none>"
    notify(
        TELEGRAM,
        build_safety_net_blocked_message(
            APPLE_ID_LABEL, RESULT.expected_uid, RESULT.expected_gid, SAMPLE_TEXT
        ),
    )
    BLOCKED_MARKER.write_text("blocked\n", encoding="utf-8")
    log_line(
        LOG_FILE,
        "debug",
        f"Safety net blocked marker written: path={BLOCKED_MARKER.as_posix()}.",
    )
    return False


# ------------------------------------------------------------------------------
# This function polls Telegram and returns one raw command batch plus cursor
# and message timing metadata.
#
# 1. "TELEGRAM" is Telegram configuration.
# 2. "USERNAME" is command prefix.
# 3. "UPDATE_OFFSET" is update offset cursor.
#
# Returns: "CommandPollBatch" for startup or active command ingestion.
# ------------------------------------------------------------------------------
def poll_command_batch(
    TELEGRAM: TelegramConfig,
    USERNAME: str,
    UPDATE_OFFSET: int | None,
    LOG_FILE: Path | None = None,
) -> command_runtime.CommandPollBatch:
    FETCH_UPDATES_FN = fetch_updates

    if UPDATE_OFFSET is not None and UPDATE_OFFSET < 0:
        FETCH_UPDATES_FN = (
            lambda TELEGRAM_CONFIG, OFFSET: fetch_updates(
                TELEGRAM_CONFIG,
                OFFSET,
                TIMEOUT=0,
                LOG_LINE_FN=log_line,
                LOG_FILE=LOG_FILE,
            )
        )
    else:
        FETCH_UPDATES_FN = (
            lambda TELEGRAM_CONFIG, OFFSET: fetch_updates(
                TELEGRAM_CONFIG,
                OFFSET,
                LOG_LINE_FN=log_line,
                LOG_FILE=LOG_FILE,
            )
        )

    return command_runtime.poll_command_batch(
        TELEGRAM,
        USERNAME,
        UPDATE_OFFSET,
        DEPS=command_runtime.CommandPollingDeps(
            fetch_updates_fn=FETCH_UPDATES_FN,
            parse_command_fn=parse_command,
        ),
    )


# ------------------------------------------------------------------------------
# This function executes one backup pass and persists refreshed manifest data.
#
# 1. "CLIENT" is iCloud client wrapper.
# 2. "CONFIG" is runtime configuration.
# 3. "TELEGRAM" is Telegram integration configuration.
# 4. "LOG_FILE" is worker log destination.
#
# Returns: "BackupRunResult" for the completed backup pass.
# ------------------------------------------------------------------------------
def run_backup(
    CLIENT: ICloudDriveClient,
    CONFIG: AppConfig,
    TELEGRAM: TelegramConfig,
    LOG_FILE: Path,
    TRIGGER: str,
) -> backup_runtime.BackupRunResult:
    APPLE_ID_LABEL = format_apple_id_label(CONFIG.icloud_email)
    SCHEDULE_LINE = format_schedule_line(CONFIG, TRIGGER)
    return backup_runtime.run_backup(
        CLIENT,
        CONFIG,
        TELEGRAM,
        LOG_FILE,
        APPLE_ID_LABEL,
        SCHEDULE_LINE,
        DEPS=backup_runtime.BackupRuntimeDeps(
            load_manifest_fn=lambda PATH: load_manifest(PATH, LOG_FILE),
            save_manifest_fn=lambda PATH, MANIFEST: save_manifest(
                PATH,
                MANIFEST,
                LOG_FILE,
            ),
            log_line_fn=log_line,
            notify_fn=notify,
            get_build_detail_fn=backup_runtime.get_build_detail,
            format_duration_fn=backup_runtime.format_duration_clock,
            format_speed_fn=backup_runtime.format_average_speed,
            perform_sync_fn=perform_incremental_sync,
        ),
    )


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
#
# Returns: "CommandHandleResult" for the handled command.
# ------------------------------------------------------------------------------
def handle_command(
    COMMAND: str,
    ARGS: str,
    CONFIG: AppConfig,
    CLIENT: ICloudDriveClient,
    AUTH_STATE: AuthState,
    IS_AUTHENTICATED: bool,
    TELEGRAM: TelegramConfig,
) -> command_runtime.CommandHandleResult:
    APPLE_ID_LABEL = format_apple_id_label(CONFIG.icloud_email)
    return command_runtime.handle_command(
        COMMAND,
        ARGS,
        CONFIG,
        CLIENT,
        AUTH_STATE,
        IS_AUTHENTICATED,
        TELEGRAM,
        APPLE_ID_LABEL,
        DEPS=command_runtime.CommandRuntimeDeps(
            attempt_auth_fn=attempt_auth,
            notify_fn=notify,
            save_auth_state_fn=(
                lambda PATH, STATE: save_auth_state(
                    PATH,
                    STATE,
                    CONFIG.worker_log_path,
                )
            ),
            log_line_fn=log_line,
            log_file_path=CONFIG.worker_log_path,
        ),
    )


# ------------------------------------------------------------------------------
# This function sends the standard container-stopped notification.
#
# 1. "TELEGRAM" is Telegram integration configuration.
# 2. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 3. "STOP_STATUS" is the final worker stop summary.
#
# Returns: None.
# ------------------------------------------------------------------------------
def notify_container_stopped(
    TELEGRAM: TelegramConfig,
    APPLE_ID_LABEL: str,
    STOP_STATUS: str,
) -> None:
    notify(
        TELEGRAM,
        build_container_stopped_message(APPLE_ID_LABEL, STOP_STATUS),
    )


# ------------------------------------------------------------------------------
# This function is the worker entrypoint used by the container launcher.
#
# Returns: Non-zero on startup validation/runtime failure.
# ------------------------------------------------------------------------------
def main() -> int:
    CONFIG = load_config()
    LOG_FILE = CONFIG.worker_log_path
    TELEGRAM = TelegramConfig(CONFIG.telegram_bot_token, CONFIG.telegram_chat_id)
    RUNTIME_CONTEXT: WorkerRuntimeContext | None = None
    HEARTBEAT_UPDATER: HeartbeatUpdater | None = None
    STOP_STATUS = "Worker process exited."

    try:
        log_line(
            LOG_FILE,
            "debug",
            "Worker bootstrap started: "
            f"config_dir={CONFIG.config_dir.as_posix()}, "
            f"output_dir={CONFIG.output_dir.as_posix()}, "
            f"logs_dir={CONFIG.logs_dir.as_posix()}, "
            f"run_once={CONFIG.run_once}.",
        )
        configure_keyring(CONFIG.config_dir)
        log_line(
            LOG_FILE,
            "debug",
            f"Keyring configured: config_dir={CONFIG.config_dir.as_posix()}.",
        )
        STORED_EMAIL, STORED_PASSWORD = load_credentials(
            CONFIG.keychain_service_name,
            CONFIG.container_username,
        )
        log_line(
            LOG_FILE,
            "debug",
            "Stored credential lookup completed: "
            f"email_present={bool(STORED_EMAIL)}, "
            f"password_present={bool(STORED_PASSWORD)}.",
        )
        CONFIG = replace(
            CONFIG,
            icloud_email=CONFIG.icloud_email or STORED_EMAIL,
            icloud_password=CONFIG.icloud_password or STORED_PASSWORD,
        )
        RUNTIME_CONTEXT = WorkerRuntimeContext(
            config=CONFIG,
            telegram=TELEGRAM,
            log_file=LOG_FILE,
            apple_id_label=format_apple_id_label(CONFIG.icloud_email),
        )

        ERRORS = validate_config(CONFIG)
        log_line(
            LOG_FILE,
            "debug",
            f"Configuration validation completed: errors={len(ERRORS)}.",
        )

        if ERRORS:
            for LINE in ERRORS:
                log_line(LOG_FILE, "error", LINE)

            return 1

        HEARTBEAT_UPDATER = start_heartbeat_updater(
            CONFIG.heartbeat_path,
            LOG_FILE,
            CONFIG.heartbeat_max_age_seconds,
        )
        log_line(
            LOG_FILE,
            "debug",
            f"Heartbeat updater started: path={CONFIG.heartbeat_path.as_posix()}.",
        )

        notify(
            RUNTIME_CONTEXT.telegram,
            build_container_started_message(RUNTIME_CONTEXT.apple_id_label),
        )

        log_line(LOG_FILE, "debug", "Creating iCloud client.")
        CLIENT = ICloudDriveClient(RUNTIME_CONTEXT.config)
        AUTH_STATE = load_auth_state(RUNTIME_CONTEXT.config.auth_state_path, LOG_FILE)
        log_line(
            LOG_FILE,
            "debug",
            "Auth state loaded: "
            f"path={RUNTIME_CONTEXT.config.auth_state_path.as_posix()}, "
            f"auth_pending={AUTH_STATE.auth_pending}, "
            f"reauth_pending={AUTH_STATE.reauth_pending}, "
            f"reminder_stage={AUTH_STATE.reminder_stage}.",
        )
        RUNTIME_RESULT = worker_runtime.run_worker_runtime(
            RUNTIME_CONTEXT,
            CLIENT,
            AUTH_STATE,
            worker_runtime.WorkerRuntimeDeps(
                attempt_auth_fn=attempt_auth,
                process_reauth_reminders_fn=(
                    lambda AUTH_STATE, AUTH_STATE_PATH, TELEGRAM, USERNAME, DAYS: (
                        process_reauth_reminders(
                            AUTH_STATE,
                            AUTH_STATE_PATH,
                            TELEGRAM,
                            USERNAME,
                            DAYS,
                            LOG_FILE,
                        )
                    )
                ),
                poll_command_batch_fn=(
                    lambda TELEGRAM_CONFIG, USERNAME, UPDATE_OFFSET: poll_command_batch(
                        TELEGRAM_CONFIG,
                        USERNAME,
                        UPDATE_OFFSET,
                        LOG_FILE,
                    )
                ),
                handle_command_fn=handle_command,
                enforce_safety_net_fn=enforce_safety_net,
                run_backup_fn=run_backup,
                notify_fn=notify,
                log_line_fn=log_line,
                get_next_run_epoch_fn=get_next_run_epoch,
                build_one_shot_waiting_for_auth_message_fn=(
                    worker_runtime.build_one_shot_waiting_for_auth_message
                ),
                build_backup_skipped_auth_incomplete_message_fn=(
                    worker_runtime.build_backup_skipped_auth_incomplete_message
                ),
                build_backup_skipped_reauth_pending_message_fn=(
                    worker_runtime.build_backup_skipped_reauth_pending_message
                ),
                check_runtime_liveness_fn=(
                    lambda: HEARTBEAT_UPDATER.get_liveness_failure(
                        worker_runtime.time.time()
                    )
                ),
                time_fn=worker_runtime.time.time,
                sleep_fn=worker_runtime.time.sleep,
            ),
        )
        STOP_STATUS = RUNTIME_RESULT.stop_status
        return RUNTIME_RESULT.exit_code
    finally:
        if RUNTIME_CONTEXT is None:
            APPLE_ID_LABEL = format_apple_id_label(CONFIG.icloud_email)
            notify_container_stopped(TELEGRAM, APPLE_ID_LABEL, STOP_STATUS)
        else:
            notify_container_stopped(
                RUNTIME_CONTEXT.telegram,
                RUNTIME_CONTEXT.apple_id_label,
                STOP_STATUS,
            )
        if HEARTBEAT_UPDATER is not None:
            HEARTBEAT_UPDATER.stop()
            log_line(
                LOG_FILE,
                "debug",
                f"Heartbeat updater stopped: path={CONFIG.heartbeat_path.as_posix()}.",
            )


if __name__ == "__main__":
    raise SystemExit(main())
