# ------------------------------------------------------------------------------
# This test module verifies Telegram message template builders.
# ------------------------------------------------------------------------------

import unittest

from app.telegram_messages import (
    build_authentication_complete_message,
    build_authentication_failed_message,
    build_authentication_required_message,
    build_backup_complete_message,
    build_backup_requested_message,
    build_backup_skipped_auth_incomplete_message,
    build_backup_skipped_reauth_pending_message,
    build_backup_started_message,
    build_container_started_message,
    build_container_stopped_message,
    build_one_shot_waiting_for_auth_message,
    build_reauth_reminder_message,
    build_reauthentication_required_for_apple_id_message,
    build_reauthentication_required_message,
    build_safety_net_blocked_message,
    get_auth_command_lines,
)


# ------------------------------------------------------------------------------
# These tests verify message-template output for all Telegram notifications.
# ------------------------------------------------------------------------------
class TestTelegramMessages(unittest.TestCase):
    def test_get_auth_command_lines(self) -> None:
        RESULT = get_auth_command_lines("alice")
        self.assertEqual(
            RESULT, ["Send `alice auth 123456`", "Or `alice reauth 123456`"]
        )

    def test_build_authentication_complete_message(self) -> None:
        MESSAGE = build_authentication_complete_message("alice@example.com", "ok")
        self.assertIn("*🔒 PCD Drive - Authentication complete*", MESSAGE)
        self.assertIn("Authenticated for Apple ID alice@example.com.", MESSAGE)
        self.assertIn("ok", MESSAGE)

    def test_build_authentication_required_message(self) -> None:
        MESSAGE = build_authentication_required_message("alice@example.com", "alice")
        self.assertIn("*🔑 PCD Drive - Authentication required*", MESSAGE)
        self.assertIn("Send `alice auth 123456`", MESSAGE)
        self.assertIn("Or `alice reauth 123456`", MESSAGE)

    def test_build_authentication_failed_message(self) -> None:
        MESSAGE = build_authentication_failed_message("alice@example.com", "Bad credentials")
        self.assertIn("*❌ PCD Drive - Authentication failed*", MESSAGE)
        self.assertIn("Bad credentials", MESSAGE)
        self.assertNotIn("Reason:", MESSAGE)

    def test_build_safety_net_blocked_message(self) -> None:
        MESSAGE = build_safety_net_blocked_message(
            "alice@example.com", 1000, 1000, "/output/path"
        )
        self.assertIn("*⚠️ PCD Drive - Safety net blocked*", MESSAGE)
        self.assertIn("Expected uid 1000, gid 1000", MESSAGE)
        self.assertIn("Sample mismatches: /output/path", MESSAGE)

    def test_build_reauthentication_required_message(self) -> None:
        MESSAGE = build_reauthentication_required_message("alice")
        self.assertIn("*🔑 PCD Drive - Reauthentication required*", MESSAGE)
        self.assertIn("Reauthentication is due within two days.", MESSAGE)
        self.assertIn("Send `alice auth 123456`", MESSAGE)

    def test_build_reauthentication_required_for_apple_id_message(self) -> None:
        MESSAGE = build_reauthentication_required_for_apple_id_message(
            "alice@example.com", "alice"
        )
        self.assertIn("*🔑 PCD Drive - Reauthentication required*", MESSAGE)
        self.assertIn("Reauthentication required for Apple ID alice@example.com.", MESSAGE)
        self.assertIn("Or `alice reauth 123456`", MESSAGE)

    def test_build_reauth_reminder_message(self) -> None:
        MESSAGE = build_reauth_reminder_message("alice")
        self.assertIn("*📣 PCD Drive - Reauth reminder*", MESSAGE)
        self.assertIn("Reauthentication will be required within five days.", MESSAGE)
        self.assertIn("Send `alice auth 123456`", MESSAGE)

    def test_build_backup_started_message(self) -> None:
        MESSAGE = build_backup_started_message(
            "alice@example.com", "Scheduled every 60 minutes."
        )
        self.assertIn("*⬇️ PCD Drive - Backup started*", MESSAGE)
        self.assertIn("Files downloading for Apple ID alice@example.com.", MESSAGE)
        self.assertIn("Scheduled every 60 minutes.", MESSAGE)

    def test_build_backup_complete_message(self) -> None:
        MESSAGE = build_backup_complete_message(
            "alice@example.com",
            [
                "Transferred: 1/1",
                "Deleted: 0 files, 0 directories",
                "Skipped: 0",
                "Errors: 0",
            ],
        )
        self.assertIn("*📦 PCD Drive - Backup complete*", MESSAGE)
        self.assertIn("Backup finished for Apple ID alice@example.com.", MESSAGE)
        self.assertIn("Transferred: 1/1", MESSAGE)
        self.assertIn("Deleted: 0 files, 0 directories", MESSAGE)

    def test_build_backup_requested_message(self) -> None:
        MESSAGE = build_backup_requested_message("alice@example.com")
        self.assertIn("*📥 PCD Drive - Backup requested*", MESSAGE)
        self.assertIn("Manual backup requested for Apple ID alice@example.com.", MESSAGE)

    def test_build_one_shot_waiting_for_auth_message(self) -> None:
        MESSAGE = build_one_shot_waiting_for_auth_message("alice@example.com", 15)
        self.assertIn("*🔑 PCD Drive - Authentication required*", MESSAGE)
        self.assertIn("The wait window is 15 mins.", MESSAGE)

    def test_build_backup_skipped_auth_incomplete_message(self) -> None:
        MESSAGE = build_backup_skipped_auth_incomplete_message("alice@example.com")
        self.assertIn("*⏭️ PCD Drive - Backup skipped*", MESSAGE)
        self.assertIn("Authentication incomplete.", MESSAGE)
        self.assertNotIn("Reason:", MESSAGE)

    def test_build_backup_skipped_reauth_pending_message(self) -> None:
        MESSAGE = build_backup_skipped_reauth_pending_message("alice@example.com")
        self.assertIn("*⏭️ PCD Drive - Backup skipped*", MESSAGE)
        self.assertIn("Reauthentication pending.", MESSAGE)
        self.assertNotIn("Reason:", MESSAGE)

    def test_build_container_started_message(self) -> None:
        MESSAGE = build_container_started_message("alice@example.com")
        self.assertIn("*🟢 PCD Drive - Container started*", MESSAGE)
        self.assertIn("Initialising authentication and backup checks.", MESSAGE)

    def test_build_container_stopped_message(self) -> None:
        MESSAGE = build_container_stopped_message(
            "alice@example.com", "Run completed and container exited."
        )
        self.assertIn("*🛑 PCD Drive - Container stopped*", MESSAGE)
        self.assertIn("Run completed and container exited.", MESSAGE)
