# ------------------------------------------------------------------------------
# This module handles Telegram Bot API messaging and command polling for
# backup control.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import requests
from typing import Any, Callable


# ------------------------------------------------------------------------------
# This data class defines token and chat settings for Telegram integration.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


# ------------------------------------------------------------------------------
# This data class represents a parsed command accepted from Telegram updates.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandEvent:
    command: str
    args: str
    update_id: int
    message_epoch: int


# ------------------------------------------------------------------------------
# This data class captures the outcome of a Telegram send attempt.
#
# N.B.
# This keeps transport success, API-level success, and failure detail together
# so runtime callers can log the exact failure without re-parsing responses.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class SendMessageResult:
    success: bool
    disabled: bool = False
    failure_detail: str = ""


# ------------------------------------------------------------------------------
# This function builds a Bot API endpoint from a token and method name.
#
# 1. "TOKEN" is the bot token.
# 2. "METHOD" is the Bot API method name.
#
# Returns: Fully-qualified HTTPS URL for the selected method.
# ------------------------------------------------------------------------------
def get_endpoint(TOKEN: str, METHOD: str) -> str:
    return f"https://api.telegram.org/bot{TOKEN}/{METHOD}"


# ------------------------------------------------------------------------------
# This function validates Telegram API success from the HTTP response body.
#
# 1. "RESPONSE" is the HTTP response returned by the Bot API call.
#
# Returns: True only when the Bot API confirms success.
# ------------------------------------------------------------------------------
def response_is_ok(RESPONSE: Any) -> bool:
    if not RESPONSE.ok:
        return False

    try:
        PAYLOAD = RESPONSE.json()
    except ValueError:
        return False

    return bool(PAYLOAD.get("ok"))


# ------------------------------------------------------------------------------
# This function extracts a Telegram API failure description from a response.
#
# 1. "RESPONSE" is the HTTP response returned by the Bot API call.
#
# Returns: Human-readable API failure detail.
# ------------------------------------------------------------------------------
def get_failure_detail(RESPONSE: Any) -> str:
    try:
        PAYLOAD = RESPONSE.json()
    except ValueError:
        return "Telegram API returned invalid JSON."

    DESCRIPTION = str(PAYLOAD.get("description", "")).strip()

    if DESCRIPTION:
        return f"Telegram API rejected the request: {DESCRIPTION}"

    return "Telegram API rejected the request without a description."


# ------------------------------------------------------------------------------
# This function sends a Telegram message and returns a structured result.
#
# 1. "CONFIG" carries token and chat configuration.
# 2. "TEXT" is message body.
# 3. "TIMEOUT" is request timeout in seconds.
#
# Returns: Structured send outcome including failure detail.
#
# Notes: Telegram Bot API reference:
# https://core.telegram.org/bots/api#sendmessage
# ------------------------------------------------------------------------------
def send_message_result(
    CONFIG: TelegramConfig,
    TEXT: str,
    TIMEOUT: int = 20,
) -> SendMessageResult:
    if not CONFIG.bot_token:
        return SendMessageResult(
            success=False,
            disabled=True,
            failure_detail="Telegram bot token is not configured.",
        )

    if not CONFIG.chat_id:
        return SendMessageResult(
            success=False,
            disabled=True,
            failure_detail="Telegram chat ID is not configured.",
        )

    PAYLOAD = {
        "chat_id": CONFIG.chat_id,
        "text": TEXT,
    }

    try:
        RESPONSE = requests.post(
            get_endpoint(CONFIG.bot_token, "sendMessage"),
            json=PAYLOAD,
            timeout=TIMEOUT,
        )
    except requests.RequestException as ERROR:
        return SendMessageResult(
            success=False,
            failure_detail=(
                "Telegram request failed: "
                f"{type(ERROR).__name__}: {ERROR}"
            ),
        )

    if response_is_ok(RESPONSE):
        return SendMessageResult(success=True)

    return SendMessageResult(
        success=False,
        failure_detail=get_failure_detail(RESPONSE),
    )


# ------------------------------------------------------------------------------
# This function sends a Telegram message and returns success state.
#
# 1. "CONFIG" carries token and chat configuration.
# 2. "TEXT" is message body.
# 3. "TIMEOUT" is request timeout in seconds.
#
# Returns: True on successful HTTP/API response, otherwise False.
# ------------------------------------------------------------------------------
def send_message(CONFIG: TelegramConfig, TEXT: str, TIMEOUT: int = 20) -> bool:
    return send_message_result(CONFIG, TEXT, TIMEOUT).success


# ------------------------------------------------------------------------------
# This function writes a Telegram polling debug line when logging is available.
#
# 1. "LOG_LINE_FN" is an optional logger callback.
# 2. "LOG_FILE" is the optional worker log destination.
# 3. "MESSAGE" is the already-redacted debug detail to write.
#
# Returns: None.
# ------------------------------------------------------------------------------
def log_telegram_debug(
    LOG_LINE_FN: Callable[[Path, str, str], None] | None,
    LOG_FILE: Path | None,
    MESSAGE: str,
) -> None:
    if LOG_LINE_FN is None or LOG_FILE is None:
        return

    LOG_LINE_FN(LOG_FILE, "debug", MESSAGE)


# ------------------------------------------------------------------------------
# This function requests recent updates with optional offset tracking.
#
# 1. "CONFIG" carries token and chat configuration.
# 2. "OFFSET" is update offset.
# 3. "TIMEOUT" is long-poll timeout in seconds.
# 4. "LOG_LINE_FN" is an optional logger callback.
# 5. "LOG_FILE" is the optional worker log destination.
#
# Returns: List of update dictionaries from Telegram, or empty list on errors.
#
# Notes: Telegram Bot API reference:
# https://core.telegram.org/bots/api#getupdates
# ------------------------------------------------------------------------------
def fetch_updates(
    CONFIG: TelegramConfig,
    OFFSET: int | None,
    TIMEOUT: int = 30,
    LOG_LINE_FN: Callable[[Path, str, str], None] | None = None,
    LOG_FILE: Path | None = None,
) -> list[dict[str, Any]]:
    if not CONFIG.bot_token:
        log_telegram_debug(
            LOG_LINE_FN,
            LOG_FILE,
            "Telegram update poll skipped: reason=bot_token_missing.",
        )
        return []

    if not CONFIG.chat_id:
        log_telegram_debug(
            LOG_LINE_FN,
            LOG_FILE,
            "Telegram update poll skipped: reason=chat_id_missing.",
        )
        return []

    PARAMS: dict[str, Any] = {"timeout": TIMEOUT}

    if OFFSET is not None:
        PARAMS["offset"] = OFFSET

    log_telegram_debug(
        LOG_LINE_FN,
        LOG_FILE,
        "Telegram update poll started: "
        f"offset={OFFSET}, "
        f"timeout={TIMEOUT}.",
    )

    try:
        RESPONSE = requests.get(
            get_endpoint(CONFIG.bot_token, "getUpdates"),
            params=PARAMS,
            timeout=TIMEOUT + 5,
        )
    except requests.RequestException as ERROR:
        log_telegram_debug(
            LOG_LINE_FN,
            LOG_FILE,
            "Telegram update poll failed: "
            "reason=request_exception, "
            f"error_type={type(ERROR).__name__}.",
        )
        return []

    if not response_is_ok(RESPONSE):
        log_telegram_debug(
            LOG_LINE_FN,
            LOG_FILE,
            "Telegram update poll failed: reason=api_rejected_or_bad_json.",
        )
        return []

    PAYLOAD = RESPONSE.json()
    RESULT = PAYLOAD.get("result", [])

    if not isinstance(RESULT, list):
        log_telegram_debug(
            LOG_LINE_FN,
            LOG_FILE,
            "Telegram update poll failed: reason=result_not_list.",
        )
        return []

    log_telegram_debug(
        LOG_LINE_FN,
        LOG_FILE,
        f"Telegram update poll completed: updates={len(RESULT)}.",
    )
    return RESULT


# ------------------------------------------------------------------------------
# This function parses a command for a matching username prefix and chat.
#
# 1. "UPDATE" is a Telegram update payload.
# 2. "USERNAME" is command prefix.
# 3. "EXPECTED_CHAT_ID" restricts accepted chats.
#
# Returns: Parsed "CommandEvent" when valid, otherwise None.
#
# Notes: Update payload structure follows Telegram Bot API documentation:
# https://core.telegram.org/bots/api#update
# ------------------------------------------------------------------------------
def parse_command(
    UPDATE: dict[str, Any],
    USERNAME: str,
    EXPECTED_CHAT_ID: str,
) -> CommandEvent | None:
    if not EXPECTED_CHAT_ID:
        return None

    UPDATE_ID = int(UPDATE.get("update_id", 0))
    MESSAGE = UPDATE.get("message")

    if not isinstance(MESSAGE, dict):
        return None

    CHAT = MESSAGE.get("chat", {})
    CHAT_ID = str(CHAT.get("id", ""))

    if CHAT_ID != EXPECTED_CHAT_ID:
        return None

    TEXT = str(MESSAGE.get("text", "")).strip()

    if not TEXT:
        return None

    PREFIX = f"{USERNAME} "

    if not TEXT.lower().startswith(PREFIX.lower()):
        return None

    BODY = TEXT[len(PREFIX) :].strip()

    if not BODY:
        return None

    PARTS = BODY.split(maxsplit=1)
    COMMAND = PARTS[0].lower()
    ARGS = PARTS[1] if len(PARTS) == 2 else ""

    if COMMAND not in {"backup", "auth", "reauth"}:
        return None

    return CommandEvent(
        command=COMMAND,
        args=ARGS,
        update_id=UPDATE_ID,
        message_epoch=int(MESSAGE.get("date", 0)),
    )
