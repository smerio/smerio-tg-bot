import logging
import requests
from typing import Optional
import config

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"

def send_message(chat_id: int | str, text: str, parse_mode: str = "HTML", reply_markup: Optional[dict] = None) -> Optional[dict]:
    """Send a message to a Telegram chat.
    
    If HTML parsing fails, automatically retries in plain text to ensure delivery.
    """
    token = config.TELEGRAM_BOT_TOKEN
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        resp = requests.post(
            _API.format(token=token, method="sendMessage"),
            json=payload,
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Telegram sendMessage failed: %s", data)
            # Fallback if HTML parsing failed
            if parse_mode == "HTML" and "parse" in data.get("description", "").lower():
                logger.warning("HTML parsing failed, retrying in plain text...")
                fallback_payload = payload.copy()
                fallback_payload.pop("parse_mode", None)
                resp = requests.post(
                    _API.format(token=token, method="sendMessage"),
                    json=fallback_payload,
                    timeout=10,
                )
                data = resp.json()
            if data.get("ok"):
                return data.get("result")
            logger.error("Telegram sendMessage absolute failure: %s", data)
            return None
        return data.get("result")
    except Exception as e:
        logger.exception("Failed to send message to Telegram")
        return None

def edit_message(chat_id: int | str, message_id: int, text: str, parse_mode: str = "HTML", reply_markup: Optional[dict] = None) -> Optional[dict]:
    """Edit an existing bot message."""
    token = config.TELEGRAM_BOT_TOKEN
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    try:
        resp = requests.post(
            _API.format(token=token, method="editMessageText"),
            json=payload,
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Telegram editMessageText failed: %s", data)
            # Fallback if HTML parsing failed
            if parse_mode == "HTML" and "parse" in data.get("description", "").lower():
                logger.warning("HTML parsing failed on edit, retrying in plain text...")
                fallback_payload = payload.copy()
                fallback_payload.pop("parse_mode", None)
                resp = requests.post(
                    _API.format(token=token, method="editMessageText"),
                    json=fallback_payload,
                    timeout=10,
                )
                data = resp.json()
            if data.get("ok"):
                return data.get("result")
            logger.error("Telegram editMessageText absolute failure: %s", data)
            return None
        return data.get("result")
    except Exception as e:
        logger.exception("Failed to edit message in Telegram")
        return None

def answer_callback_query(callback_query_id: str, text: Optional[str] = None, show_alert: bool = False) -> bool:
    """Answer a Telegram callback query to clear the loading spinner."""
    token = config.TELEGRAM_BOT_TOKEN
    payload = {
        "callback_query_id": callback_query_id,
    }
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert

    try:
        resp = requests.post(
            _API.format(token=token, method="answerCallbackQuery"),
            json=payload,
            timeout=10,
        )
        data = resp.json()
        return bool(data.get("ok"))
    except Exception as e:
        logger.exception("Failed to answer callback query")
        return False
