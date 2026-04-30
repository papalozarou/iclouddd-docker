# ------------------------------------------------------------------------------
# This test module verifies scheduler parsing, formatting, and next-run logic.
# ------------------------------------------------------------------------------

from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from app.config import AppConfig
from app.scheduler import (
    calculate_next_daily_run_epoch,
    calculate_next_monthly_run_epoch,
    calculate_next_twice_weekly_run_epoch,
    calculate_next_weekly_run_epoch,
    format_schedule_description,
    format_schedule_line,
    get_monthly_weekday_day,
    get_next_run_epoch,
    parse_daily,
    parse_weekday,
    parse_weekday_list,
)


# ------------------------------------------------------------------------------
# This function creates an "AppConfig" fixture for direct scheduler tests.
# ------------------------------------------------------------------------------
def build_scheduler_config(**OVERRIDES: object) -> AppConfig:
    BASE_CONFIG = AppConfig(
        container_username="alice",
        icloud_email="alice@example.com",
        icloud_password="password",
        telegram_bot_token="token",
        telegram_chat_id="12345",
        keychain_service_name="pyiclodoc-drive",
        run_once=False,
        schedule_mode="interval",
        schedule_backup_time="02:00",
        schedule_weekdays="monday,thursday",
        schedule_monthly_week="first",
        schedule_interval_minutes=360,
        backup_delete_removed=False,
        traversal_workers=1,
        sync_workers=0,
        download_chunk_mib=4,
        healthcheck_max_age_seconds=900,
        reauth_interval_days=30,
        output_dir=Path("/tmp/output"),
        config_dir=Path("/tmp/config"),
        logs_dir=Path("/tmp/logs"),
        manifest_path=Path("/tmp/config/pyiclodoc-drive-manifest.json"),
        auth_state_path=Path("/tmp/config/pyiclodoc-drive-auth_state.json"),
        heartbeat_path=Path("/tmp/logs/pyiclodoc-drive-heartbeat.txt"),
        safety_net_done_path=Path("/tmp/config/pyiclodoc-drive-safety_net_done.flag"),
        safety_net_blocked_path=Path("/tmp/config/pyiclodoc-drive-safety_net_blocked.flag"),
        cookie_dir=Path("/tmp/config/cookies"),
        session_dir=Path("/tmp/config/session"),
        icloudpd_compat_dir=Path("/tmp/config/icloudpd"),
        safety_net_sample_size=200,
    )

    CONFIG_VALUES = BASE_CONFIG.__dict__.copy()
    CONFIG_VALUES.update(OVERRIDES)
    return AppConfig(**CONFIG_VALUES)


# ------------------------------------------------------------------------------
# These tests verify direct schedule parsing helpers.
# ------------------------------------------------------------------------------
class TestSchedulerParsing(unittest.TestCase):
# --------------------------------------------------------------------------
# This test confirms daily time parsing trims whitespace and returns
# hour-minute tuples.
# --------------------------------------------------------------------------
    def test_parse_daily_accepts_valid_trimmed_value(self) -> None:
        self.assertEqual(parse_daily(" 02:30 "), (2, 30))

# --------------------------------------------------------------------------
# This test confirms malformed daily values are rejected.
# --------------------------------------------------------------------------
    def test_parse_daily_rejects_malformed_value(self) -> None:
        self.assertIsNone(parse_daily("2pm"))
        self.assertIsNone(parse_daily("24:00"))
        self.assertIsNone(parse_daily("aa:00"))
        self.assertIsNone(parse_daily("02:60"))

# --------------------------------------------------------------------------
# This test confirms weekday parsing is case-insensitive.
# --------------------------------------------------------------------------
    def test_parse_weekday_accepts_mixed_case(self) -> None:
        self.assertEqual(parse_weekday("Thursday"), 3)

# --------------------------------------------------------------------------
# This test confirms duplicate or count-mismatched weekday lists fail.
# --------------------------------------------------------------------------
    def test_parse_weekday_list_rejects_duplicate_and_count_mismatch(self) -> None:
        self.assertIsNone(parse_weekday_list("monday,monday", 2))
        self.assertIsNone(parse_weekday_list("monday", 2))


# ------------------------------------------------------------------------------
# These tests verify next-run calculations for each supported mode.
# ------------------------------------------------------------------------------
class TestSchedulerEpochCalculation(unittest.TestCase):
# --------------------------------------------------------------------------
# This test confirms daily schedules advance to the next day after the
# target time has passed.
# --------------------------------------------------------------------------
    def test_calculate_next_daily_run_moves_to_next_day(self) -> None:
        NOW_VALUE = datetime(2026, 3, 10, 3, 0, tzinfo=timezone.utc)

        NEXT_EPOCH = calculate_next_daily_run_epoch(NOW_VALUE, "02:00")

        self.assertEqual(
            NEXT_EPOCH,
            int(datetime(2026, 3, 11, 2, 0, tzinfo=timezone.utc).timestamp()),
        )

# --------------------------------------------------------------------------
# This test confirms invalid daily schedule text falls back to the current
# timestamp.
# --------------------------------------------------------------------------
    def test_calculate_next_daily_run_returns_now_for_invalid_time(self) -> None:
        NOW_VALUE = datetime(2026, 3, 10, 3, 0, tzinfo=timezone.utc)

        NEXT_EPOCH = calculate_next_daily_run_epoch(NOW_VALUE, "bad")

        self.assertEqual(NEXT_EPOCH, int(NOW_VALUE.timestamp()))

# --------------------------------------------------------------------------
# This test confirms weekly schedules advance by seven days when the
# same-day target time has already passed.
# --------------------------------------------------------------------------
    def test_calculate_next_weekly_run_wraps_after_passed_same_day_time(self) -> None:
        NOW_VALUE = datetime(2026, 3, 9, 3, 0, tzinfo=timezone.utc)

        NEXT_EPOCH = calculate_next_weekly_run_epoch(NOW_VALUE, "monday", "02:00")

        self.assertEqual(
            NEXT_EPOCH,
            int(datetime(2026, 3, 16, 2, 0, tzinfo=timezone.utc).timestamp()),
        )

# --------------------------------------------------------------------------
# This test confirms invalid weekly schedule inputs fall back to the current
# timestamp.
# --------------------------------------------------------------------------
    def test_calculate_next_weekly_run_returns_now_for_invalid_inputs(self) -> None:
        NOW_VALUE = datetime(2026, 3, 9, 3, 0, tzinfo=timezone.utc)

        NEXT_EPOCH = calculate_next_weekly_run_epoch(NOW_VALUE, "funday", "bad")

        self.assertEqual(NEXT_EPOCH, int(NOW_VALUE.timestamp()))

# --------------------------------------------------------------------------
# This test confirms twice-weekly schedules pick the earliest valid
# candidate from the configured pair.
# --------------------------------------------------------------------------
    def test_calculate_next_twice_weekly_run_picks_earliest_candidate(self) -> None:
        NOW_VALUE = datetime(2026, 3, 9, 1, 0, tzinfo=timezone.utc)

        NEXT_EPOCH = calculate_next_twice_weekly_run_epoch(
            NOW_VALUE,
            "monday,thursday",
            "02:00",
        )

        self.assertEqual(
            NEXT_EPOCH,
            int(datetime(2026, 3, 9, 2, 0, tzinfo=timezone.utc).timestamp()),
        )

# --------------------------------------------------------------------------
# This test confirms invalid twice-weekly weekday lists fall back to the
# current timestamp.
# --------------------------------------------------------------------------
    def test_calculate_next_twice_weekly_run_returns_now_for_invalid_weekdays(self) -> None:
        NOW_VALUE = datetime(2026, 3, 9, 1, 0, tzinfo=timezone.utc)

        NEXT_EPOCH = calculate_next_twice_weekly_run_epoch(
            NOW_VALUE,
            "monday",
            "02:00",
        )

        self.assertEqual(NEXT_EPOCH, int(NOW_VALUE.timestamp()))

# --------------------------------------------------------------------------
# This test confirms monthly weekday lookup supports the "last" token.
# --------------------------------------------------------------------------
    def test_get_monthly_weekday_day_returns_last_weekday(self) -> None:
        self.assertEqual(get_monthly_weekday_day(2026, 2, 0, "last"), 23)

# --------------------------------------------------------------------------
# This test confirms monthly weekday lookup returns None for impossible
# weekday values in the "last" branch.
# --------------------------------------------------------------------------
    def test_get_monthly_weekday_day_returns_none_for_invalid_last_weekday(self) -> None:
        self.assertIsNone(get_monthly_weekday_day(2026, 2, 9, "last"))

# --------------------------------------------------------------------------
# This test confirms monthly weekday lookup returns None for impossible
# weekday values in ordinal branches.
# --------------------------------------------------------------------------
    def test_get_monthly_weekday_day_returns_none_for_invalid_ordinal_weekday(self) -> None:
        self.assertIsNone(get_monthly_weekday_day(2026, 2, 9, "first"))

# --------------------------------------------------------------------------
# This test confirms monthly weekday lookup returns None for unknown
# month-week tokens.
# --------------------------------------------------------------------------
    def test_get_monthly_weekday_day_returns_none_for_invalid_monthly_week(self) -> None:
        self.assertIsNone(get_monthly_weekday_day(2026, 2, 0, "fifth"))

# --------------------------------------------------------------------------
# This test confirms monthly schedules advance into the next month once
# the current month's target has already passed.
# --------------------------------------------------------------------------
    def test_calculate_next_monthly_run_advances_to_next_month(self) -> None:
        NOW_VALUE = datetime(2026, 3, 3, 3, 0, tzinfo=timezone.utc)

        NEXT_EPOCH = calculate_next_monthly_run_epoch(
            NOW_VALUE,
            "monday",
            "first",
            "02:00",
        )

        self.assertEqual(
            NEXT_EPOCH,
            int(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc).timestamp()),
        )

# --------------------------------------------------------------------------
# This test confirms invalid monthly schedule inputs fall back to the
# current timestamp.
# --------------------------------------------------------------------------
    def test_calculate_next_monthly_run_returns_now_for_invalid_inputs(self) -> None:
        NOW_VALUE = datetime(2026, 3, 3, 3, 0, tzinfo=timezone.utc)

        NEXT_EPOCH = calculate_next_monthly_run_epoch(
            NOW_VALUE,
            "funday",
            "first",
            "bad",
        )

        self.assertEqual(NEXT_EPOCH, int(NOW_VALUE.timestamp()))

# --------------------------------------------------------------------------
# This test confirms monthly scheduling skips months that do not produce a
# usable weekday match and uses the first later valid candidate.
# --------------------------------------------------------------------------
    def test_calculate_next_monthly_run_skips_invalid_candidate_month(self) -> None:
        NOW_VALUE = datetime(2026, 3, 3, 3, 0, tzinfo=timezone.utc)

        with patch("app.scheduler.get_monthly_weekday_day", side_effect=[None, 6]):
            NEXT_EPOCH = calculate_next_monthly_run_epoch(
                NOW_VALUE,
                "monday",
                "first",
                "02:00",
            )

        self.assertEqual(
            NEXT_EPOCH,
            int(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc).timestamp()),
        )

# --------------------------------------------------------------------------
# This test confirms monthly scheduling falls back to the current timestamp
# when no candidate month yields a valid target day.
# --------------------------------------------------------------------------
    def test_calculate_next_monthly_run_returns_now_when_all_candidates_fail(self) -> None:
        NOW_VALUE = datetime(2026, 3, 3, 3, 0, tzinfo=timezone.utc)

        with patch("app.scheduler.get_monthly_weekday_day", return_value=None):
            NEXT_EPOCH = calculate_next_monthly_run_epoch(
                NOW_VALUE,
                "monday",
                "first",
                "02:00",
            )

        self.assertEqual(NEXT_EPOCH, int(NOW_VALUE.timestamp()))

# --------------------------------------------------------------------------
# This test confirms interval scheduling uses the provided epoch and
# interval minutes directly.
# --------------------------------------------------------------------------
    def test_get_next_run_epoch_interval_uses_now_epoch(self) -> None:
        CONFIG = build_scheduler_config(schedule_mode="interval", schedule_interval_minutes=360)

        self.assertEqual(get_next_run_epoch(CONFIG, 1000), 22600)

# --------------------------------------------------------------------------
# This test confirms daily mode delegates to the local-time helper path.
# --------------------------------------------------------------------------
    def test_get_next_run_epoch_daily_uses_now_local(self) -> None:
        CONFIG = build_scheduler_config(schedule_mode="daily", schedule_backup_time="02:00")
        NOW_VALUE = datetime(2026, 3, 10, 1, 0, tzinfo=timezone.utc)

        with patch("app.scheduler.now_local", return_value=NOW_VALUE):
            RESULT = get_next_run_epoch(CONFIG, 1234)

        self.assertEqual(
            RESULT,
            int(datetime(2026, 3, 10, 2, 0, tzinfo=timezone.utc).timestamp()),
        )

# --------------------------------------------------------------------------
# This test confirms weekly mode falls back to "NOW_EPOCH" when weekday
# parsing is invalid.
# --------------------------------------------------------------------------
    def test_get_next_run_epoch_weekly_returns_now_epoch_for_invalid_weekday(self) -> None:
        CONFIG = build_scheduler_config(schedule_mode="weekly", schedule_weekdays="funday")

        self.assertEqual(get_next_run_epoch(CONFIG, 4321), 4321)

# --------------------------------------------------------------------------
# This test confirms weekly mode delegates to the weekly helper when the
# configured weekday is valid.
# --------------------------------------------------------------------------
    def test_get_next_run_epoch_weekly_uses_weekly_helper(self) -> None:
        CONFIG = build_scheduler_config(
            schedule_mode="weekly",
            schedule_weekdays="thursday",
            schedule_backup_time="02:00",
        )

        with patch("app.scheduler.now_local", return_value=datetime(2026, 3, 9, 1, 0, tzinfo=timezone.utc)):
            RESULT = get_next_run_epoch(CONFIG, 4321)

        self.assertEqual(
            RESULT,
            int(datetime(2026, 3, 12, 2, 0, tzinfo=timezone.utc).timestamp()),
        )

# --------------------------------------------------------------------------
# This test confirms twice-weekly mode delegates to the twice-weekly helper.
# --------------------------------------------------------------------------
    def test_get_next_run_epoch_twice_weekly_uses_twice_weekly_helper(self) -> None:
        CONFIG = build_scheduler_config(
            schedule_mode="twice_weekly",
            schedule_weekdays="monday,thursday",
            schedule_backup_time="02:00",
        )

        with patch("app.scheduler.now_local", return_value=datetime(2026, 3, 9, 1, 0, tzinfo=timezone.utc)):
            RESULT = get_next_run_epoch(CONFIG, 4321)

        self.assertEqual(
            RESULT,
            int(datetime(2026, 3, 9, 2, 0, tzinfo=timezone.utc).timestamp()),
        )

# --------------------------------------------------------------------------
# This test confirms monthly mode delegates to the monthly helper when the
# configured weekday list is valid.
# --------------------------------------------------------------------------
    def test_get_next_run_epoch_monthly_uses_monthly_helper(self) -> None:
        CONFIG = build_scheduler_config(
            schedule_mode="monthly",
            schedule_weekdays="monday",
            schedule_monthly_week="first",
            schedule_backup_time="02:00",
        )

        with patch("app.scheduler.now_local", return_value=datetime(2026, 3, 1, 1, 0, tzinfo=timezone.utc)):
            RESULT = get_next_run_epoch(CONFIG, 4321)

        self.assertEqual(
            RESULT,
            int(datetime(2026, 3, 2, 2, 0, tzinfo=timezone.utc).timestamp()),
        )

# --------------------------------------------------------------------------
# This test confirms monthly mode falls back to "NOW_EPOCH" when weekday
# parsing is invalid.
# --------------------------------------------------------------------------
    def test_get_next_run_epoch_monthly_returns_now_epoch_for_invalid_weekday(self) -> None:
        CONFIG = build_scheduler_config(schedule_mode="monthly", schedule_weekdays="funday")

        self.assertEqual(get_next_run_epoch(CONFIG, 4321), 4321)


# ------------------------------------------------------------------------------
# These tests verify human-readable schedule wording used in Telegram.
# ------------------------------------------------------------------------------
class TestSchedulerFormatting(unittest.TestCase):
# --------------------------------------------------------------------------
# This test confirms one-shot descriptions explicitly state that the
# configured schedule is ignored.
# --------------------------------------------------------------------------
    def test_format_schedule_description_for_one_shot(self) -> None:
        CONFIG = build_scheduler_config()

        self.assertEqual(
            format_schedule_description(CONFIG, "one-shot"),
            "One-shot run – configured schedule is ignored",
        )

# --------------------------------------------------------------------------
# This test confirms scheduled interval output is rendered as a sentence.
# --------------------------------------------------------------------------
    def test_format_schedule_line_for_scheduled_interval(self) -> None:
        CONFIG = build_scheduler_config(schedule_mode="interval", schedule_interval_minutes=360)

        self.assertEqual(
            format_schedule_line(CONFIG, "scheduled"),
            "Scheduled every 360 minutes.",
        )

# --------------------------------------------------------------------------
# This test confirms manual output keeps the follow-on schedule sentence.
# --------------------------------------------------------------------------
    def test_format_schedule_line_for_manual_daily(self) -> None:
        CONFIG = build_scheduler_config(schedule_mode="daily", schedule_backup_time="02:00")

        self.assertEqual(
            format_schedule_line(CONFIG, "manual"),
            "Manual, then daily at 02:00.",
        )

# --------------------------------------------------------------------------
# This test confirms scheduled weekly output preserves weekday and time.
# --------------------------------------------------------------------------
    def test_format_schedule_line_for_scheduled_weekly(self) -> None:
        CONFIG = build_scheduler_config(
            schedule_mode="weekly",
            schedule_weekdays="thursday",
            schedule_backup_time="02:00",
        )

        self.assertEqual(
            format_schedule_line(CONFIG, "scheduled"),
            "Scheduled weekly on thursday at 02:00.",
        )

# --------------------------------------------------------------------------
# This test confirms twice-weekly descriptions use both weekday names.
# --------------------------------------------------------------------------
    def test_format_schedule_description_for_twice_weekly(self) -> None:
        CONFIG = build_scheduler_config(
            schedule_mode="twice_weekly",
            schedule_weekdays="monday,thursday",
            schedule_backup_time="02:00",
        )

        self.assertEqual(
            format_schedule_description(CONFIG, "scheduled"),
            "Twice weekly on Monday and Thursday at 02:00",
        )

# --------------------------------------------------------------------------
# This test confirms monthly schedule output is locked to the current
# Telegram wording.
# --------------------------------------------------------------------------
    def test_format_schedule_line_for_scheduled_monthly(self) -> None:
        CONFIG = build_scheduler_config(
            schedule_mode="monthly",
            schedule_weekdays="monday",
            schedule_monthly_week="first",
            schedule_backup_time="02:00",
        )

        self.assertEqual(
            format_schedule_line(CONFIG, "scheduled"),
            "Scheduled monthly on the first monday at 02:00.",
        )

# --------------------------------------------------------------------------
# This test confirms unknown schedule modes fall back to a plain configured
# mode description.
# --------------------------------------------------------------------------
    def test_format_schedule_description_for_unknown_mode(self) -> None:
        CONFIG = build_scheduler_config(schedule_mode="custom")

        self.assertEqual(
            format_schedule_description(CONFIG, "scheduled"),
            "Configured mode custom",
        )

# --------------------------------------------------------------------------
# This test confirms unknown trigger values fall back to sentence-style
# schedule descriptions.
# --------------------------------------------------------------------------
    def test_format_schedule_line_for_unknown_trigger(self) -> None:
        CONFIG = build_scheduler_config(schedule_mode="daily", schedule_backup_time="02:00")

        self.assertEqual(
            format_schedule_line(CONFIG, "adhoc"),
            "Daily at 02:00.",
        )
