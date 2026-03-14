# ------------------------------------------------------------------------------
# This module centralises Telegram notification message formatting and templates.
# ------------------------------------------------------------------------------

from __future__ import annotations


# ------------------------------------------------------------------------------
# This function formats a Telegram event with icon, title, summary, and details.
#
# 1. "ICON" is the message icon.
# 2. "TITLE" is the event title.
# 3. "SUMMARY_LINE" is the summary sentence.
# 4. "DETAIL_LINES" is optional detail content.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def format_telegram_event(
    ICON: str,
    TITLE: str,
    SUMMARY_LINE: str,
    DETAIL_LINES: list[str] | None = None,
) -> str:
    LINES = [f"*{ICON} PCD Drive - {TITLE}*", "", SUMMARY_LINE]

    if DETAIL_LINES:
        LINES.extend([""] + DETAIL_LINES)

    return "\n".join(LINES)


# ------------------------------------------------------------------------------
# This function returns standard auth command detail lines for Telegram prompts.
#
# 1. "USERNAME" is the configured command prefix.
#
# Returns: Standard auth and reauth command lines.
# ------------------------------------------------------------------------------
def get_auth_command_lines(USERNAME: str) -> list[str]:
    return [
        f"Send `{USERNAME} auth 123456`",
        f"Or `{USERNAME} reauth 123456`",
    ]


# ------------------------------------------------------------------------------
# This function builds the authentication completed notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 2. "DETAILS" is the authentication result detail text.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_authentication_complete_message(APPLE_ID_LABEL: str, DETAILS: str) -> str:
    return format_telegram_event(
        "🔒",
        "Authentication complete",
        f"Authenticated for Apple ID {APPLE_ID_LABEL}.",
        [DETAILS],
    )


# ------------------------------------------------------------------------------
# This function builds the authentication required notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 2. "USERNAME" is the configured command prefix.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_authentication_required_message(APPLE_ID_LABEL: str, USERNAME: str) -> str:
    return format_telegram_event(
        "🔑",
        "Authentication required",
        f"Authentication required for Apple ID {APPLE_ID_LABEL}.",
        get_auth_command_lines(USERNAME),
    )


# ------------------------------------------------------------------------------
# This function builds the authentication failed notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 2. "DETAILS" is the authentication failure detail text.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_authentication_failed_message(APPLE_ID_LABEL: str, DETAILS: str) -> str:
    return format_telegram_event(
        "❌",
        "Authentication failed",
        f"Authentication failed for Apple ID {APPLE_ID_LABEL}.",
        [DETAILS],
    )


# ------------------------------------------------------------------------------
# This function builds the safety-net blocked notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 2. "EXPECTED_UID" is the expected uid.
# 3. "EXPECTED_GID" is the expected gid.
# 4. "SAMPLE_TEXT" is summarised mismatch sample text.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_safety_net_blocked_message(
    APPLE_ID_LABEL: str,
    EXPECTED_UID: int,
    EXPECTED_GID: int,
    SAMPLE_TEXT: str,
) -> str:
    return format_telegram_event(
        "⚠️",
        "Safety net blocked",
        f"Backup blocked for Apple ID {APPLE_ID_LABEL}.",
        [
            "Permission mismatches detected in existing files.",
            f"Expected uid {EXPECTED_UID}, gid {EXPECTED_GID}",
            f"Sample mismatches: {SAMPLE_TEXT}",
        ],
    )


# ------------------------------------------------------------------------------
# This function builds the reauthentication required reminder message.
#
# 1. "USERNAME" is the configured command prefix.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_reauthentication_required_message(USERNAME: str) -> str:
    return format_telegram_event(
        "🔑",
        "Reauthentication required",
        "Reauthentication is due within two days.",
        get_auth_command_lines(USERNAME),
    )


# ------------------------------------------------------------------------------
# This function builds an on-demand reauthentication required message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 2. "USERNAME" is the configured command prefix.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_reauthentication_required_for_apple_id_message(
    APPLE_ID_LABEL: str, USERNAME: str
) -> str:
    return format_telegram_event(
        "🔑",
        "Reauthentication required",
        f"Reauthentication required for Apple ID {APPLE_ID_LABEL}.",
        get_auth_command_lines(USERNAME),
    )


# ------------------------------------------------------------------------------
# This function builds the five-day reauthentication reminder message.
#
# 1. "USERNAME" is the configured command prefix.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_reauth_reminder_message(USERNAME: str) -> str:
    return format_telegram_event(
        "📣",
        "Reauth reminder",
        "Reauthentication will be required within five days.",
        get_auth_command_lines(USERNAME),
    )


# ------------------------------------------------------------------------------
# This function builds the backup started notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 2. "SCHEDULE_LINE" is the human-readable schedule line.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_backup_started_message(APPLE_ID_LABEL: str, SCHEDULE_LINE: str) -> str:
    return format_telegram_event(
        "⬇️",
        "Backup started",
        f"Files downloading for Apple ID {APPLE_ID_LABEL}.",
        [SCHEDULE_LINE],
    )


# ------------------------------------------------------------------------------
# This function builds the backup completed notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 2. "STATUS_LINES" are backup result details.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_backup_complete_message(APPLE_ID_LABEL: str, STATUS_LINES: list[str]) -> str:
    return format_telegram_event(
        "📦",
        "Backup complete",
        f"Backup finished for Apple ID {APPLE_ID_LABEL}.",
        STATUS_LINES,
    )


# ------------------------------------------------------------------------------
# This function builds the manual backup requested notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_backup_requested_message(APPLE_ID_LABEL: str) -> str:
    return format_telegram_event(
        "📥",
        "Backup requested",
        f"Manual backup requested for Apple ID {APPLE_ID_LABEL}.",
        ["Worker queued backup to run now."],
    )


# ------------------------------------------------------------------------------
# This function builds the one-shot authentication wait notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 2. "WAIT_MINUTES" is the one-shot wait window in minutes.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_one_shot_waiting_for_auth_message(
    APPLE_ID_LABEL: str, WAIT_MINUTES: int
) -> str:
    return format_telegram_event(
        "🔑",
        "Authentication required",
        f"Authentication required for Apple ID {APPLE_ID_LABEL}.",
        [
            "One-shot mode is waiting for an auth command before backup.",
            f"The wait window is {WAIT_MINUTES} mins.",
        ],
    )


# ------------------------------------------------------------------------------
# This function builds the backup skipped due to auth incomplete message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_backup_skipped_auth_incomplete_message(APPLE_ID_LABEL: str) -> str:
    return format_telegram_event(
        "⏭️",
        "Backup skipped",
        f"Backup skipped for Apple ID {APPLE_ID_LABEL}.",
        ["Authentication incomplete."],
    )


# ------------------------------------------------------------------------------
# This function builds the backup skipped due to reauth pending message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_backup_skipped_reauth_pending_message(APPLE_ID_LABEL: str) -> str:
    return format_telegram_event(
        "⏭️",
        "Backup skipped",
        f"Backup skipped for Apple ID {APPLE_ID_LABEL}.",
        ["Reauthentication pending."],
    )


# ------------------------------------------------------------------------------
# This function builds the container started notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_container_started_message(APPLE_ID_LABEL: str) -> str:
    return format_telegram_event(
        "🟢",
        "Container started",
        f"Worker started for Apple ID {APPLE_ID_LABEL}.",
        ["Initialising authentication and backup checks."],
    )


# ------------------------------------------------------------------------------
# This function builds the container stopped notification message.
#
# 1. "APPLE_ID_LABEL" is the formatted Apple ID label.
# 2. "STOP_STATUS" is the final worker status line.
#
# Returns: Rendered Telegram message body.
# ------------------------------------------------------------------------------
def build_container_stopped_message(APPLE_ID_LABEL: str, STOP_STATUS: str) -> str:
    return format_telegram_event(
        "🛑",
        "Container stopped",
        f"Worker stopped for Apple ID {APPLE_ID_LABEL}.",
        [STOP_STATUS],
    )
