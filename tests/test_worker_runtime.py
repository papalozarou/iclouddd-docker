# ------------------------------------------------------------------------------
# This test module verifies the worker-loop control flow in "app.worker_runtime".
# ------------------------------------------------------------------------------

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from app.config import AppConfig
from app.runtime_context import WorkerRuntimeContext
from app.state import AuthState
from app.telegram_bot import TelegramConfig
from app.worker_runtime import run_scheduled_worker_loop


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
        keychain_service_name="icloud-drive-backup",
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
        return SimpleNamespace(
            process_reauth_reminders_fn=lambda AUTH_STATE, *_: AUTH_STATE,
            process_commands_fn=PROCESS_COMMANDS_FN,
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
# This test confirms a skipped manual backup due to incomplete authentication
# is cleared after one notification.
# --------------------------------------------------------------------------
    def test_run_scheduled_worker_loop_clears_manual_request_after_auth_skip(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            NOTIFY = Mock()
            PROCESS_COMMANDS = Mock(side_effect=[([("backup", "")], None), ([], None)])
            HANDLE_COMMAND = Mock(return_value=(AUTH_STATE, False, True))
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
                    AUTH_STATE,
                    False,
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
            PROCESS_COMMANDS = Mock(side_effect=[([("backup", "")], None), ([], None)])
            HANDLE_COMMAND = Mock(return_value=(AUTH_STATE, True, True))
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
                    AUTH_STATE,
                    True,
                    DEPS,
                )

        NOTIFY.assert_called_once_with(TELEGRAM, "reauth pending for alice@example.com")
        ENFORCE_SAFETY_NET.assert_not_called()
        DEPS.run_backup_fn.assert_not_called()

# --------------------------------------------------------------------------
# This test confirms a skipped manual backup due to a safety-net block is
# cleared after one blocked run.
# --------------------------------------------------------------------------
    def test_run_scheduled_worker_loop_clears_manual_request_after_safety_net_skip(self) -> None:
        with tempfile.TemporaryDirectory() as TMPDIR:
            RUNTIME_CONTEXT, _TELEGRAM, AUTH_STATE = self.build_runtime_context(TMPDIR)
            NOTIFY = Mock()
            PROCESS_COMMANDS = Mock(side_effect=[([("backup", "")], None), ([], None)])
            HANDLE_COMMAND = Mock(return_value=(AUTH_STATE, True, True))
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
                    AUTH_STATE,
                    True,
                    DEPS,
                )

        NOTIFY.assert_not_called()
        self.assertEqual(ENFORCE_SAFETY_NET.call_count, 1)
        DEPS.run_backup_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
