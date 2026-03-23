# ------------------------------------------------------------------------------
# This test module verifies the worker-loop control flow in "app.worker_runtime".
# ------------------------------------------------------------------------------

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from app.auth_runtime import AuthAttemptResult
from app.command_runtime import CommandHandleResult, CommandPollBatch
from app.backup_runtime import BackupRunResult
from app.config import AppConfig
from app.runtime_context import WorkerRuntimeContext
from app.state import AuthState
from app.telegram_bot import CommandEvent, TelegramConfig
from app.worker_runtime import (
    CommandBatchReadResult,
    CommandPollingState,
    WorkerAuthState,
    WorkerRunResult,
    drain_startup_command_backlog,
    read_command_batch,
    run_one_shot_worker,
    run_scheduled_worker_loop,
    run_worker_runtime,
    wait_for_one_shot_auth,
)


class StopWorkerLoop(Exception):
    pass


# ------------------------------------------------------------------------------
# This function creates an "AppConfig" fixture for worker runtime tests.
# ------------------------------------------------------------------------------
def build_config_for_worker_runtime(TMPDIR: str) -> AppConfig:
    ROOT_DIR = Path(TMPDIR)
    CONFIG_DIR = ROOT_DIR / "config"
    OUTPUT_DIR = ROOT_DIR / "output"
    LOGS_DIR = ROOT_DIR / "logs"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        container_username="alice",
        icloud_email="alice@example.com",
        icloud_password="password",
        telegram_bot_token="token",
        telegram_chat_id="12345",
        keychain_service_name="pyiclodoc-drive",
        run_once=False,
        schedule_mode="daily",
        schedule_backup_time="02:00",
        schedule_weekdays="monday",
        schedule_monthly_week="first",
        schedule_interval_minutes=60,
        backup_delete_removed=False,
        traversal_workers=1,
        sync_workers=0,
        download_chunk_mib=4,
        reauth_interval_days=30,
        output_dir=OUTPUT_DIR,
        config_dir=CONFIG_DIR,
        logs_dir=LOGS_DIR,
        manifest_path=CONFIG_DIR / "pyiclodoc-drive-manifest.json",
        auth_state_path=CONFIG_DIR / "pyiclodoc-drive-auth_state.json",
        heartbeat_path=LOGS_DIR / "pyiclodoc-drive-heartbeat.txt",
        safety_net_done_path=CONFIG_DIR / "pyiclodoc-drive-safety_net_done.flag",
        safety_net_blocked_path=CONFIG_DIR / "pyiclodoc-drive-safety_net_blocked.flag",
        cookie_dir=CONFIG_DIR / "cookies",
        session_dir=CONFIG_DIR / "session",
        icloudpd_compat_dir=CONFIG_DIR / "icloudpd",
        safety_net_sample_size=200,
    )


# ------------------------------------------------------------------------------
# These tests verify skipped manual requests do not stay latched in the loop.
# ------------------------------------------------------------------------------
class TestWorkerRuntime(unittest.TestCase):
# --------------------------------------------------------------------------
# This function builds a worker runtime context plus shared dependency values
# for worker-loop tests.
#
# Returns: Tuple "(runtime_context, telegram, auth_state)".
# --------------------------------------------------------------------------
    def build_runtime_context(
        self,
        TMPDIR: str,
        *,
        reauth_pending: bool = False,
    ) -> tuple[WorkerRuntimeContext, TelegramConfig, AuthState]:
        CONFIG = build_config_for_worker_runtime(TMPDIR)
        TELEGRAM = TelegramConfig("token", "12345")
        AUTH_STATE = AuthState(
            "1970-01-01T00:00:00+00:00",
            False,
            reauth_pending,
            "none",
        )
        RUNTIME_CONTEXT = WorkerRuntimeContext(
            CONFIG=CONFIG,
            TELEGRAM=TELEGRAM,
            LOG_FILE=CONFIG.logs_dir / "pyiclodoc-drive-worker.log",
            APPLE_ID_LABEL="alice@example.com",
        )
        return RUNTIME_CONTEXT, TELEGRAM, AUTH_STATE

# --------------------------------------------------------------------------
# This function builds one command batch fixture for polling tests.
#
# 1. "COMMANDS" is a list of "(command, args, message_epoch)" tuples.
# 2. "NEXT_UPDATE_OFFSET" is the next polling cursor.
# 3. "MAX_MESSAGE_EPOCH" optionally overrides the batch max message epoch.
#
# Returns: "CommandPollBatch" fixture.
# --------------------------------------------------------------------------
    def build_command_batch(
        self,
        COMMANDS: list[tuple[str, str, int]],
        NEXT_UPDATE_OFFSET: int | None,
        *,
        MAX_MESSAGE_EPOCH: int | None = None,
    ) -> CommandPollBatch:
        EVENTS = [
            CommandEvent(
                command=COMMAND,
                args=ARGS,
                update_id=INDEX + 1,
                message_epoch=MESSAGE_EPOCH,
            )
            for INDEX, (COMMAND, ARGS, MESSAGE_EPOCH) in enumerate(COMMANDS)
        ]
        if MAX_MESSAGE_EPOCH is None:
            MAX_MESSAGE_EPOCH = max((EVENT.message_epoch for EVENT in EVENTS), default=0)
        return CommandPollBatch(EVENTS, NEXT_UPDATE_OFFSET, MAX_MESSAGE_EPOCH)

# --------------------------------------------------------------------------
# This function builds worker-loop dependencies with controllable callbacks.
#
# 1. "PROCESS_COMMANDS_FN" returns Telegram commands plus next offset.
# 2. "HANDLE_COMMAND_FN" handles one command and returns request state.
# 3. "ENFORCE_SAFETY_NET_FN" applies the safety gate before backup.
# 4. "NOTIFY_FN" captures operator notifications for assertions.
# 5. "SLEEP_FN" controls loop exit for tests.
#
# Returns: Namespace exposing worker dependency fields.
# --------------------------------------------------------------------------
    def build_deps(
        self,
        *,
        PROCESS_COMMANDS_FN,
        HANDLE_COMMAND_FN,
        ENFORCE_SAFETY_NET_FN,
        NOTIFY_FN,
        SLEEP_FN,
    ) -> SimpleNamespace:
        def poll_command_batch_fn(*ARGS):
            RESULT = PROCESS_COMMANDS_FN(*ARGS)

            if isinstance(RESULT, CommandPollBatch):
                return RESULT

            COMMANDS, NEXT_UPDATE_OFFSET = RESULT
            return self.build_command_batch(
                [(COMMAND, COMMAND_ARGS, 0) for COMMAND, COMMAND_ARGS in COMMANDS],
                NEXT_UPDATE_OFFSET,
            )

        return SimpleNamespace(
            process_reauth_reminders_fn=lambda AUTH_STATE, *_: AUTH_STATE,
            poll_command_batch_fn=poll_command_batch_fn,
            handle_command_fn=HANDLE_COMMAND_FN,
            enforce_safety_net_fn=ENFORCE_SAFETY_NET_FN,
            run_backup_fn=Mock(),
            notify_fn=NOTIFY_FN,
            log_line_fn=Mock(),
            get_next_run_epoch_fn=lambda *_: 200,
            build_backup_skipped_auth_incomplete_message_fn=lambda APPLE_ID_LABEL: (
                f"auth incomplete for {APPLE_ID_LABEL}"
            ),
            build_backup_skipped_reauth_pending_message_fn=lambda APPLE_ID_LABEL: (
                f"reauth pending for {APPLE_ID_LABEL}"
            ),
            time_fn=lambda: 100,
            sleep_fn=SLEEP_FN,
        )

# --------------------------------------------------------------------------
# This test confirms one-shot auth wait exits at the configured timeout
# when authentication never completes.
# --------------------------------------------------------------------------
    def test_wait_for_one_shot_auth_returns_after_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            PROCESS_COMMANDS = Mock(return_value=([], None))
            HANDLE_COMMAND = Mock()
            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=HANDLE_COMMAND,
                ENFORCE_SAFETY_NET_FN=Mock(return_value=True),
                NOTIFY_FN=Mock(),
                SLEEP_FN=Mock(),
            )
            DEPS.time_fn = Mock(side_effect=[0, 900])

            RESULT = wait_for_one_shot_auth(
                RUNTIME_CONTEXT,
                Mock(),
                WorkerAuthState(auth_state=AUTH_STATE, is_authenticated=False),
                DEPS,
            )

        self.assertEqual(RESULT.auth_state, AUTH_STATE)
        self.assertFalse(RESULT.is_authenticated)
        PROCESS_COMMANDS.assert_called_once_with(
            RUNTIME_CONTEXT.TELEGRAM,
            RUNTIME_CONTEXT.CONFIG.container_username,
            None,
        )
        HANDLE_COMMAND.assert_not_called()
        DEPS.sleep_fn.assert_not_called()

# --------------------------------------------------------------------------
# This test confirms one-shot auth wait processes commands until auth
# completes and then returns the updated state.
# --------------------------------------------------------------------------
    def test_wait_for_one_shot_auth_processes_commands_until_authenticated(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            UPDATED_STATE = AuthState(
                "2026-03-15T12:00:00+00:00",
                False,
                False,
                "none",
            )
            PROCESS_COMMANDS = Mock(
                side_effect=[
                    ([], None),
                    ([("auth", "123456")], 9),
                ]
            )
            HANDLE_COMMAND = Mock(
                return_value=CommandHandleResult(
                    auth_state=UPDATED_STATE,
                    is_authenticated=True,
                    backup_requested=False,
                    reason_code="authenticated",
                    operator_detail="ok",
                )
            )
            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=HANDLE_COMMAND,
                ENFORCE_SAFETY_NET_FN=Mock(return_value=True),
                NOTIFY_FN=Mock(),
                SLEEP_FN=Mock(),
            )
            DEPS.time_fn = Mock(side_effect=[0, 1, 2])

            RESULT = wait_for_one_shot_auth(
                RUNTIME_CONTEXT,
                Mock(),
                WorkerAuthState(auth_state=AUTH_STATE, is_authenticated=False),
                DEPS,
            )

        self.assertEqual(RESULT.auth_state, UPDATED_STATE)
        self.assertTrue(RESULT.is_authenticated)
        self.assertEqual(PROCESS_COMMANDS.call_count, 2)
        HANDLE_COMMAND.assert_called_once()
        DEPS.sleep_fn.assert_called_once()

# --------------------------------------------------------------------------
# This test confirms startup backlog drain discards all historical command
# batches and returns the final polling state for active command polling.
# --------------------------------------------------------------------------
    def test_drain_startup_command_backlog_returns_next_offset(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, _AUTH_STATE = self.build_runtime_context(TMPDIR)
            PROCESS_COMMANDS = Mock(
                side_effect=[
                    self.build_command_batch([("backup", "", 50)], 41),
                    self.build_command_batch([("auth", "123456", 100)], 42),
                ]
            )
            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=Mock(),
                ENFORCE_SAFETY_NET_FN=Mock(return_value=True),
                NOTIFY_FN=Mock(),
                SLEEP_FN=Mock(),
            )

            RESULT = drain_startup_command_backlog(
                RUNTIME_CONTEXT,
                DEPS,
                STARTUP_CUTOVER_EPOCH=100,
            )

        self.assertEqual(
            RESULT,
            CommandPollingState(
                phase="live_polling",
                next_update_offset=42,
                buffered_commands=(("auth", "123456"),),
            ),
        )
        self.assertEqual(PROCESS_COMMANDS.call_count, 2)
        self.assertEqual(PROCESS_COMMANDS.call_args_list[0].args[2], None)
        self.assertEqual(PROCESS_COMMANDS.call_args_list[1].args[2], 41)
        PROCESS_COMMANDS.assert_any_call(
            RUNTIME_CONTEXT.TELEGRAM,
            RUNTIME_CONTEXT.CONFIG.container_username,
            None,
        )

# --------------------------------------------------------------------------
# This test confirms startup backlog drain stops when live updates are seen,
# even if the current batch contains no parsed command events.
# --------------------------------------------------------------------------
    def test_drain_startup_command_backlog_stops_at_live_non_command_updates(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, _AUTH_STATE = self.build_runtime_context(TMPDIR)
            PROCESS_COMMANDS = Mock(
                side_effect=[
                    self.build_command_batch([("backup", "", 50)], 41),
                    self.build_command_batch([], 42, MAX_MESSAGE_EPOCH=100),
                ]
            )
            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=Mock(),
                ENFORCE_SAFETY_NET_FN=Mock(return_value=True),
                NOTIFY_FN=Mock(),
                SLEEP_FN=Mock(),
            )

            RESULT = drain_startup_command_backlog(
                RUNTIME_CONTEXT,
                DEPS,
                STARTUP_CUTOVER_EPOCH=100,
            )

        self.assertEqual(RESULT, CommandPollingState(phase="live_polling", next_update_offset=42))
        self.assertEqual(PROCESS_COMMANDS.call_count, 2)

# --------------------------------------------------------------------------
# This test confirms command batch reads advance and reuse one polling state.
# --------------------------------------------------------------------------
    def test_read_command_batch_reuses_one_polling_state(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, _AUTH_STATE = self.build_runtime_context(TMPDIR)
            PROCESS_COMMANDS = Mock(
                side_effect=[
                    ([("backup", "")], 9),
                    ([("auth", "123456")], 10),
                ]
            )
            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=Mock(),
                ENFORCE_SAFETY_NET_FN=Mock(return_value=True),
                NOTIFY_FN=Mock(),
                SLEEP_FN=Mock(),
            )

            FIRST_RESULT = read_command_batch(
                RUNTIME_CONTEXT,
                CommandPollingState(),
                DEPS,
                DRAIN_ONLY=True,
            )
            SECOND_RESULT = read_command_batch(
                RUNTIME_CONTEXT,
                FIRST_RESULT.polling_state,
                DEPS,
            )

        self.assertEqual(
            FIRST_RESULT.polling_state,
            CommandPollingState(phase="live_polling", next_update_offset=9),
        )
        self.assertEqual(SECOND_RESULT.commands, [("auth", "123456")])
        self.assertEqual(
            SECOND_RESULT.polling_state,
            CommandPollingState(phase="live_polling", next_update_offset=10),
        )
        self.assertEqual(PROCESS_COMMANDS.call_count, 2)
        self.assertEqual(PROCESS_COMMANDS.call_args_list[0].args[2], None)
        self.assertEqual(PROCESS_COMMANDS.call_args_list[1].args[2], 9)

# --------------------------------------------------------------------------
# This test confirms one-shot auth wait ignores startup backlog and only
# processes new commands after the drained offset.
# --------------------------------------------------------------------------
    def test_wait_for_one_shot_auth_ignores_startup_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            UPDATED_STATE = AuthState(
                "2026-03-15T12:00:00+00:00",
                False,
                False,
                "none",
            )
            PROCESS_COMMANDS = Mock(
                side_effect=[
                    self.build_command_batch([("backup", "", 50)], 9),
                    self.build_command_batch([("auth", "123456", 100)], 10),
                ]
            )
            HANDLE_COMMAND = Mock(
                return_value=CommandHandleResult(
                    auth_state=UPDATED_STATE,
                    is_authenticated=True,
                    backup_requested=False,
                    reason_code="authenticated",
                    operator_detail="ok",
                )
            )
            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=HANDLE_COMMAND,
                ENFORCE_SAFETY_NET_FN=Mock(return_value=True),
                NOTIFY_FN=Mock(),
                SLEEP_FN=Mock(),
            )
            DEPS.time_fn = Mock(side_effect=[0, 1, 2])

            RESULT = wait_for_one_shot_auth(
                RUNTIME_CONTEXT,
                Mock(),
                WorkerAuthState(auth_state=AUTH_STATE, is_authenticated=False),
                DEPS,
                100,
            )

        self.assertEqual(RESULT.auth_state, UPDATED_STATE)
        self.assertTrue(RESULT.is_authenticated)
        self.assertEqual(PROCESS_COMMANDS.call_count, 2)
        HANDLE_COMMAND.assert_called_once_with(
            "auth",
            "123456",
            RUNTIME_CONTEXT.CONFIG,
            unittest.mock.ANY,
            AUTH_STATE,
            False,
            RUNTIME_CONTEXT.TELEGRAM,
        )

# --------------------------------------------------------------------------
# This test confirms one-shot worker returns the safety-net blocked exit
# result when authentication is complete but backup is not permitted.
# --------------------------------------------------------------------------
    def test_run_one_shot_worker_returns_safety_net_blocked_result(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            NOTIFY = Mock()
            ENFORCE_SAFETY_NET = Mock(return_value=False)
            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=Mock(return_value=([], None)),
                HANDLE_COMMAND_FN=Mock(),
                ENFORCE_SAFETY_NET_FN=ENFORCE_SAFETY_NET,
                NOTIFY_FN=NOTIFY,
                SLEEP_FN=Mock(),
            )
            DEPS.build_one_shot_waiting_for_auth_message_fn = Mock(return_value="waiting")

            RESULT = run_one_shot_worker(
                RUNTIME_CONTEXT,
                Mock(),
                WorkerAuthState(auth_state=AUTH_STATE, is_authenticated=True),
                DEPS,
            )

        self.assertEqual(
            RESULT,
            WorkerRunResult(
                exit_code=4,
                stop_status="One-shot backup blocked by safety net.",
            ),
        )
        ENFORCE_SAFETY_NET.assert_called_once()
        NOTIFY.assert_not_called()
        DEPS.run_backup_fn.assert_not_called()

# --------------------------------------------------------------------------
# This test confirms a skipped manual backup due to incomplete authentication
# is cleared after one notification.
# --------------------------------------------------------------------------
    def test_run_scheduled_worker_loop_clears_manual_request_after_auth_skip(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            NOTIFY = Mock()
            PROCESS_COMMANDS = Mock(side_effect=[([], None), ([("backup", "")], 6), ([], 6)])
            HANDLE_COMMAND = Mock(
                return_value=CommandHandleResult(
                    auth_state=AUTH_STATE,
                    is_authenticated=False,
                    backup_requested=True,
                    reason_code="backup_requested",
                )
            )
            ENFORCE_SAFETY_NET = Mock(return_value=True)
            SLEEP_CALLS = {"count": 0}

            def sleep_fn(_SECONDS: float) -> None:
                SLEEP_CALLS["count"] += 1
                if SLEEP_CALLS["count"] >= 2:
                    raise StopWorkerLoop()

            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=HANDLE_COMMAND,
                ENFORCE_SAFETY_NET_FN=ENFORCE_SAFETY_NET,
                NOTIFY_FN=NOTIFY,
                SLEEP_FN=sleep_fn,
            )

            with self.assertRaises(StopWorkerLoop):
                run_scheduled_worker_loop(
                    RUNTIME_CONTEXT,
                    Mock(),
                    WorkerAuthState(auth_state=AUTH_STATE, is_authenticated=False),
                    DEPS,
                )

        NOTIFY.assert_called_once_with(TELEGRAM, "auth incomplete for alice@example.com")
        ENFORCE_SAFETY_NET.assert_not_called()
        DEPS.run_backup_fn.assert_not_called()

# --------------------------------------------------------------------------
# This test confirms a skipped manual backup due to pending reauthentication
# is cleared after one notification.
# --------------------------------------------------------------------------
    def test_run_scheduled_worker_loop_clears_manual_request_after_reauth_skip(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, TELEGRAM, AUTH_STATE = self.build_runtime_context(
                TMPDIR,
                reauth_pending=True,
            )
            NOTIFY = Mock()
            PROCESS_COMMANDS = Mock(side_effect=[([], None), ([("backup", "")], 6), ([], 6)])
            HANDLE_COMMAND = Mock(
                return_value=CommandHandleResult(
                    auth_state=AUTH_STATE,
                    is_authenticated=True,
                    backup_requested=True,
                    reason_code="backup_requested",
                )
            )
            ENFORCE_SAFETY_NET = Mock(return_value=True)
            SLEEP_CALLS = {"count": 0}

            def sleep_fn(_SECONDS: float) -> None:
                SLEEP_CALLS["count"] += 1
                if SLEEP_CALLS["count"] >= 2:
                    raise StopWorkerLoop()

            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=HANDLE_COMMAND,
                ENFORCE_SAFETY_NET_FN=ENFORCE_SAFETY_NET,
                NOTIFY_FN=NOTIFY,
                SLEEP_FN=sleep_fn,
            )

            with self.assertRaises(StopWorkerLoop):
                run_scheduled_worker_loop(
                    RUNTIME_CONTEXT,
                    Mock(),
                    WorkerAuthState(auth_state=AUTH_STATE, is_authenticated=True),
                    DEPS,
                )

        NOTIFY.assert_called_once_with(TELEGRAM, "reauth pending for alice@example.com")
        ENFORCE_SAFETY_NET.assert_not_called()
        DEPS.run_backup_fn.assert_not_called()

# --------------------------------------------------------------------------
# This test confirms scheduled runtime ignores startup backlog and processes
# only new commands after the drained offset.
# --------------------------------------------------------------------------
    def test_run_scheduled_worker_loop_ignores_startup_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            PROCESS_COMMANDS = Mock(
                side_effect=[
                    self.build_command_batch([("backup", "", 50)], 9),
                    self.build_command_batch([("backup", "", 100)], 10),
                ]
            )
            HANDLE_COMMAND = Mock(
                return_value=CommandHandleResult(
                    auth_state=AUTH_STATE,
                    is_authenticated=True,
                    backup_requested=True,
                    reason_code="backup_requested",
                )
            )

            def sleep_fn(_SECONDS: float) -> None:
                raise StopWorkerLoop()

            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=HANDLE_COMMAND,
                ENFORCE_SAFETY_NET_FN=Mock(return_value=True),
                NOTIFY_FN=Mock(),
                SLEEP_FN=sleep_fn,
            )
            DEPS.time_fn = Mock(side_effect=[100, 100])

            with self.assertRaises(StopWorkerLoop):
                run_scheduled_worker_loop(
                    RUNTIME_CONTEXT,
                    Mock(),
                    WorkerAuthState(auth_state=AUTH_STATE, is_authenticated=True),
                    DEPS,
                    100,
                )

        self.assertEqual(PROCESS_COMMANDS.call_count, 2)
        HANDLE_COMMAND.assert_called_once()
        DEPS.run_backup_fn.assert_called_once()

# --------------------------------------------------------------------------
# This test confirms a skipped manual backup due to a safety-net block is
# cleared after one blocked run.
# --------------------------------------------------------------------------
    def test_run_scheduled_worker_loop_clears_manual_request_after_safety_net_skip(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            NOTIFY = Mock()
            PROCESS_COMMANDS = Mock(side_effect=[([], None), ([("backup", "")], 6), ([], 6)])
            HANDLE_COMMAND = Mock(
                return_value=CommandHandleResult(
                    auth_state=AUTH_STATE,
                    is_authenticated=True,
                    backup_requested=True,
                    reason_code="backup_requested",
                )
            )
            ENFORCE_SAFETY_NET = Mock(return_value=False)
            SLEEP_CALLS = {"count": 0}

            def sleep_fn(_SECONDS: float) -> None:
                SLEEP_CALLS["count"] += 1
                if SLEEP_CALLS["count"] >= 2:
                    raise StopWorkerLoop()

            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=HANDLE_COMMAND,
                ENFORCE_SAFETY_NET_FN=ENFORCE_SAFETY_NET,
                NOTIFY_FN=NOTIFY,
                SLEEP_FN=sleep_fn,
            )

            with self.assertRaises(StopWorkerLoop):
                run_scheduled_worker_loop(
                    RUNTIME_CONTEXT,
                    Mock(),
                    WorkerAuthState(auth_state=AUTH_STATE, is_authenticated=True),
                    DEPS,
                )

        NOTIFY.assert_not_called()
        self.assertEqual(ENFORCE_SAFETY_NET.call_count, 1)
        DEPS.run_backup_fn.assert_not_called()

# --------------------------------------------------------------------------
# This test confirms the scheduled loop sleeps and retries when neither the
# schedule nor a manual backup request is due.
# --------------------------------------------------------------------------
    def test_run_scheduled_worker_loop_waits_when_no_backup_is_due(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            SLEEP = Mock(side_effect=StopWorkerLoop())
            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=Mock(return_value=([], None)),
                HANDLE_COMMAND_FN=Mock(),
                ENFORCE_SAFETY_NET_FN=Mock(return_value=True),
                NOTIFY_FN=Mock(),
                SLEEP_FN=SLEEP,
            )
            DEPS.time_fn = Mock(side_effect=[100, 100])
            DEPS.get_next_run_epoch_fn = Mock(return_value=200)

            with self.assertRaises(StopWorkerLoop):
                run_scheduled_worker_loop(
                    RUNTIME_CONTEXT,
                    Mock(),
                    WorkerAuthState(auth_state=AUTH_STATE, is_authenticated=True),
                    DEPS,
                )

        SLEEP.assert_called_once_with(5)
        DEPS.notify_fn.assert_not_called()
        DEPS.enforce_safety_net_fn.assert_not_called()
        DEPS.run_backup_fn.assert_not_called()

# --------------------------------------------------------------------------
# This test confirms run_worker_runtime delegates to the scheduled loop and
# returns the steady-state worker exit result.
# --------------------------------------------------------------------------
    def test_run_worker_runtime_returns_scheduled_worker_result(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            ATTEMPT_AUTH = Mock(
                return_value=AuthAttemptResult(
                    auth_state=AUTH_STATE,
                    is_authenticated=True,
                    reason_code="authenticated",
                    operator_detail="ok",
                )
            )
            PROCESS_COMMANDS = Mock(return_value=([], None))
            HANDLE_COMMAND = Mock()
            DEPS = self.build_deps(
                PROCESS_COMMANDS_FN=PROCESS_COMMANDS,
                HANDLE_COMMAND_FN=HANDLE_COMMAND,
                ENFORCE_SAFETY_NET_FN=Mock(return_value=True),
                NOTIFY_FN=Mock(),
                SLEEP_FN=Mock(),
            )
            DEPS.attempt_auth_fn = ATTEMPT_AUTH
            DEPS.log_line_fn = Mock()
            DEPS.build_one_shot_waiting_for_auth_message_fn = Mock(return_value="waiting")

            with patch("app.worker_runtime.run_scheduled_worker_loop") as RUN_LOOP:
                RESULT = run_worker_runtime(
                    RUNTIME_CONTEXT,
                    Mock(),
                    AUTH_STATE,
                    DEPS,
                )

        self.assertEqual(
            RESULT,
            WorkerRunResult(
                exit_code=0,
                stop_status="Worker process exited.",
            ),
        )
        ATTEMPT_AUTH.assert_called_once()
        RUN_LOOP.assert_called_once()
        self.assertEqual(DEPS.log_line_fn.call_count, 2)


if __name__ == "__main__":
    unittest.main()
