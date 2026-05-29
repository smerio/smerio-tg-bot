import json
import logging
import os
from datetime import datetime, timezone
import boto3

import config
import telegram_utils as tg
import smerio_client
import parser
import payload_utils

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """AWS Lambda webhook entry point for Telegram.
    
    Fast webhook execution pattern:
    1. Parse update and authenticate user ID immediately.
    2. Dispatch execution asynchronously to the same Lambda function to avoid webhook timeout.
    3. Return 200 OK to Telegram instantly.
    """
    # Async processing path: triggered by self-invocation
    if "_proc" in event:
        update = event["_proc"]
        try:
            _route_update(update)
        except Exception as e:
            logger.exception("Error in async update processor")
            # If we have a chat_id, try to report the error
            message = update.get("message") or update.get("edited_message") or update.get("callback_query", {}).get("message") or {}
            chat_id = message.get("chat", {}).get("id")
            if chat_id:
                tg.send_message(chat_id, f"❌ <i>Internal Bot Error: {e}</i>")
        return {"statusCode": 200, "body": "OK"}

    # Webhook path: parse raw update
    try:
        body = event.get("body") or "{}"
        update = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("Webhook received invalid JSON body")
        return {"statusCode": 200, "body": "OK"}

    # Zero-trust verification of Telegram Sender User ID
    message = update.get("message") or update.get("edited_message") or {}
    callback_query = update.get("callback_query") or {}
    
    from_user = None
    if message:
        from_user = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")
    elif callback_query:
        from_user = callback_query.get("from", {}).get("id")
        chat_id = callback_query.get("message", {}).get("chat", {}).get("id")

    if from_user is None or chat_id is None:
        return {"statusCode": 200, "body": "OK"}

    if from_user != config.ALLOWED_TELEGRAM_USER_ID:
        logger.warning("Unauthorized user ID access attempt: %s", from_user)
        # Return 200 OK silently to prevent Telegram retries for unauthorized attempts
        return {"statusCode": 200, "body": "OK"}

    # Self-invoke asynchronously using boto3
    try:
        boto3.client("lambda").invoke(
            FunctionName=context.function_name,
            InvocationType="Event",
            Payload=json.dumps({"_proc": update}),
        )
    except Exception:
        logger.exception("Async Lambda self-invocation failed. Processing synchronously.")
        # Fallback to synchronous execution (for local testing/dry-runs)
        try:
            _route_update(update)
        except Exception as e:
            tg.send_message(chat_id, f"❌ <i>Synchronous Processing Error: {e}</i>")

    return {"statusCode": 200, "body": "OK"}

def _route_update(update: dict) -> None:
    """Routes the authenticated Telegram update to the appropriate handler."""
    if "message" in update or "edited_message" in update:
        message = update.get("message") or update.get("edited_message")
        _handle_message(message)
    elif "callback_query" in update:
        callback_query = update.get("callback_query")
        _handle_callback_query(callback_query)

def _handle_message(message: dict) -> None:
    """Handle incoming text messages."""
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    from_user_id = message.get("from", {}).get("id")

    if not text or not chat_id:
        return

    # Check for simple start/help commands
    if text.lower() in ("/start", "/help"):
        help_text = (
            "👋 <b>Welcome to the Smerio Telegram Bot!</b>\n\n"
            "You can log transactions to Smerio by simply typing them in natural language.\n\n"
            "<b>Examples:</b>\n"
            "• <i>'spent 20$ on 2 cups of coffee in the starbucks'</i>\n"
            "• <i>'salary 3000 USD from work'</i>\n"
            "• <i>'spent 150 EUR for groceries at Lidl using debit card'</i>\n\n"
            "I will parse the transaction, map it to your Smerio accounts and categories, and ask for your confirmation before writing it to Smerio."
        )
        tg.send_message(chat_id, help_text)
        return

    # Fetch user context from Smerio
    try:
        profile = smerio_client.get_user_profile(from_user_id)
    except Exception as e:
        logger.exception("Failed to load Smerio profile")
        tg.send_message(
            chat_id,
            f"❌ <b>Smerio Connection Error:</b> Could not fetch profile context.\n"
            f"Please check that Smerio is running and your bot integration is enabled.\n\n"
            f"<i>Details: {e}</i>"
        )
        return

    # Call LLM parser
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        parsed_tx = parser.get_parser().parse(text, current_time, profile)
    except Exception as e:
        logger.exception("LLM parsing error")
        tg.send_message(chat_id, f"❌ <b>AI Parser Error:</b> Failed to analyze message.\n\n<i>Details: {e}</i>")
        return

    clarification_needed = parsed_tx.get("clarification_needed", False)
    friendly_msg = parsed_tx.get("friendly_message", "Is this correct?")
    confidence = parsed_tx.get("confidence", 0.0)

    if clarification_needed or confidence < 0.7:
        # LLM needs clarification or has low confidence: ask the user directly
        tg.send_message(chat_id, friendly_msg)
        return

    # Zero-trust validate and clean Smerio payload
    clean_tx = {
        "amount": float(parsed_tx.get("amount", 0.0)),
        "currency": parsed_tx.get("currency", profile.get("base_currency", "USD")),
        "category": parsed_tx.get("category", "Uncategorized"),
        "subcategory": parsed_tx.get("subcategory"),
        "type": parsed_tx.get("type", "Expense"),
        "notes": parsed_tx.get("notes"),
        "account_id": parsed_tx.get("account_id"),
        "date": parsed_tx.get("date")
    }

    # Encode payload statelessly inside a zero-width invisible HTML link
    invisible_link = payload_utils.encode_payload(clean_tx)
    final_message = f"{invisible_link}{friendly_msg}"

    # Inline confirm/cancel buttons
    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Yes, log it", "callback_data": "confirm"},
            {"text": "❌ No, cancel", "callback_data": "cancel"}
        ]]
    }

    # Send confirmation message
    tg.send_message(chat_id, final_message, parse_mode="HTML", reply_markup=reply_markup)

def _handle_callback_query(callback_query: dict) -> None:
    """Handle interactive inline keyboard clicks."""
    callback_query_id = callback_query.get("id")
    data = callback_query.get("data")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    original_text = message.get("text", "")
    from_user_id = callback_query.get("from", {}).get("id")

    if not callback_query_id or not chat_id or not message_id:
        return

    # Extract transaction payload statelessly from message zero-width link
    tx = payload_utils.extract_payload_from_message(message)

    if data == "confirm":
        if not tx:
            tg.answer_callback_query(callback_query_id, "❌ Error: Could not extract payload", show_alert=True)
            tg.edit_message(chat_id, message_id, f"{original_text}\n\n❌ <b>Error:</b> Could not extract stateless transaction details.")
            return

        # Prepare transaction payload for Smerio
        tx["tg_user_id"] = str(from_user_id)

        try:
            smerio_client.create_transaction(tx)
            tg.answer_callback_query(callback_query_id, "✅ Transaction logged successfully!")
            tg.edit_message(chat_id, message_id, f"{original_text}\n\n✅ <b>Logged successfully!</b>", reply_markup={"inline_keyboard": []})
        except Exception as e:
            logger.exception("Smerio write error")
            tg.answer_callback_query(callback_query_id, "❌ Failed to log transaction", show_alert=True)
            tg.edit_message(chat_id, message_id, f"{original_text}\n\n❌ <b>Smerio Error:</b> {e}", reply_markup={"inline_keyboard": []})

    elif data == "cancel":
        tg.answer_callback_query(callback_query_id, "Cancelled")
        tg.edit_message(chat_id, message_id, f"{original_text}\n\n❌ <b>Transaction cancelled.</b>", reply_markup={"inline_keyboard": []})
