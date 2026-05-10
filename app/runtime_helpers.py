# ------------------------------------------------------------------------------
# This module provides small shared runtime helpers used across worker modules.
# ------------------------------------------------------------------------------

from __future__ import annotations

from app.logger import log_console_line
from app.telegram_bot import TelegramConfig, send_message_result


# ------------------------------------------------------------------------------
# This function sends a Telegram message when integration is configured.
#
# 1. "TELEGRAM" is Telegram integration configuration.
# 2. "MESSAGE" is outgoing message content.
#
# Returns: None.
# ------------------------------------------------------------------------------
def notify(TELEGRAM: TelegramConfig, MESSAGE: str) -> None:
    RESULT = send_message_result(TELEGRAM, MESSAGE)

    if RESULT.success or RESULT.disabled:
        return

    log_console_line(
        "error",
        "Telegram notification failed: "
        f"{RESULT.failure_detail}",
    )


# ------------------------------------------------------------------------------
# This function formats a fallback-safe Apple ID label for Telegram messages.
#
# 1. "APPLE_ID" is the configured iCloud email value.
#
# Returns: Non-empty Apple ID label.
# ------------------------------------------------------------------------------
def format_apple_id_label(APPLE_ID: str) -> str:
    CLEAN_VALUE = APPLE_ID.strip()

    if CLEAN_VALUE:
        return CLEAN_VALUE

    return "<unknown>"
