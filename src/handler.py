import json
import logging
import os
from datetime import datetime, timezone
import config
import telegram_utils as tg
import smerio_client
import parser
import payload_utils

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

import re
from typing import Optional

def _find_exact_or_fuzzy_match(llm_val: Optional[str], valid_vals: list) -> Optional[str]:
    """Finds an exact or substring match in valid_vals for llm_val."""
    if not llm_val:
        return None
        
    # 1. Exact match (case sensitive)
    if llm_val in valid_vals:
        return llm_val
        
    # 2. Case-insensitive exact match
    llm_val_lower = llm_val.strip().lower()
    for val in valid_vals:
        if val.strip().lower() == llm_val_lower:
            return val
            
    # 3. Fuzzy substring match (alphanumeric cleaning)
    def clean_str(s: str) -> str:
        # Lowercase and remove all non-alphanumeric characters
        return re.sub(r'[^\w\s]', '', s.lower()).strip()
        
    llm_clean = clean_str(llm_val)
    if not llm_clean:
        return None
        
    for val in valid_vals:
        val_clean = clean_str(val)
        if not val_clean:
            continue
        # Check if one is a substring of the other (bidirectional)
        if val_clean in llm_clean or llm_clean in val_clean:
            return val
            
    return None

def _safe_replace_value(msg: str, old_val: str, new_val: str) -> str:
    """Safely replace category/subcategory name in friendly message to avoid partial-word replacement."""
    if not old_val or not new_val or old_val == new_val:
        return msg
        
    # Try common quoting patterns first
    quotes = [
        ("'", "'"),
        ('"', '"'),
        ("«", "»"),
        ("“", "”"),
        ("`", "`"),
    ]
    for q_start, q_end in quotes:
        old_quoted = f"{q_start}{old_val}{q_end}"
        if old_quoted in msg:
            new_quoted = f"{q_start}{new_val}{q_end}"
            return msg.replace(old_quoted, new_quoted)
            
    # Fallback to word-boundary-like replacement for cyrillic and latin
    pattern = re.compile(rf"(?<!\w){re.escape(old_val)}(?!\w)")
    if pattern.search(msg):
        return pattern.sub(new_val, msg)
        
    # Ultimate fallback
    if old_val in msg:
        return msg.replace(old_val, new_val)
        
    return msg

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
        import boto3
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
    """Handle incoming text or photo messages."""
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    photo = message.get("photo")
    caption = (message.get("caption") or "").strip()
    from_user_id = message.get("from", {}).get("id")

    if not chat_id:
        return

    # Process receipt photo if present
    image_bytes = None
    if photo:
        largest_photo = photo[-1]
        file_id = largest_photo.get("file_id")
        if file_id:
            tg.send_message(chat_id, "📷 <i>Reading receipt photo...</i>")
            image_bytes = tg.download_file(file_id)
            if not image_bytes:
                tg.send_message(chat_id, "❌ Failed to download receipt image from Telegram.")
                return
        text = caption
    elif not text:
        return

    # Check for simple start/help commands (only for text messages)
    if not photo and text.lower() in ("/start", "/help"):
        help_text = (
            "👋 <b>Welcome to the Smerio Telegram Bot!</b>\n\n"
            "You can log transactions to Smerio by simply typing them in natural language, or by **sending a photo of a receipt or bill**.\n\n"
            "<b>Examples:</b>\n"
            "• <i>'spent 20$ on 2 cups of coffee in the starbucks'</i>\n"
            "• <i>'salary 3000 USD from work'</i>\n"
            "• <i>[Send receipt photo] + caption: 'via Credit Card'</i>\n\n"
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
        parsed_tx = parser.get_parser().parse(text, current_time, profile, image_bytes=image_bytes)
    except Exception as e:
        logger.exception("LLM parsing error")
        tg.send_message(chat_id, f"❌ <b>AI Parser Error:</b> Failed to analyze message.\n\n<i>Details: {e}</i>")
        return

    clarification_needed = parsed_tx.get("clarification_needed", False)
    friendly_msg = parsed_tx.get("friendly_message", "Is this correct?")
    confidence = parsed_tx.get("confidence", 0.0)

    # Programmatic Zero-Trust Taxonomy Validation Safeguard
    if not clarification_needed:
        category = parsed_tx.get("category")
        subcategory = parsed_tx.get("subcategory")
        tx_type = parsed_tx.get("type", "Expense")
        
        categories_ctx = profile.get("categories", {})
        
        valid = True
        
        # 1. Validate and Match Category
        valid_categories = []
        if tx_type == "Expense":
            valid_categories = categories_ctx.get("expense_categories", [])
        elif tx_type == "Income":
            valid_categories = categories_ctx.get("income_categories", [])
        else:
            valid = False
            
        if valid:
            matched_category = _find_exact_or_fuzzy_match(category, valid_categories)
            if not matched_category:
                valid = False
            else:
                if category != matched_category:
                    logger.info("Fuzzy matched category: %r -> %r", category, matched_category)
                    friendly_msg = _safe_replace_value(friendly_msg, category, matched_category)
                    parsed_tx["category"] = matched_category
                    category = matched_category
                    
        # 2. Validate and Match Subcategory
        if valid and subcategory:
            valid_subcategories = []
            if tx_type == "Expense":
                expense_subcategories = categories_ctx.get("expense_subcategories", {})
                valid_subcategories = expense_subcategories.get(category, []) + expense_subcategories.get("", [])
            elif tx_type == "Income":
                valid_subcategories = categories_ctx.get("income_subcategories", [])
                
            matched_subcategory = _find_exact_or_fuzzy_match(subcategory, valid_subcategories)
            if not matched_subcategory:
                valid = False
            else:
                if subcategory != matched_subcategory:
                    logger.info("Fuzzy matched subcategory: %r -> %r", subcategory, matched_subcategory)
                    friendly_msg = _safe_replace_value(friendly_msg, subcategory, matched_subcategory)
                    parsed_tx["subcategory"] = matched_subcategory
                    subcategory = matched_subcategory
                    
        if not valid:
            logger.warning(
                "Programmatic taxonomy mismatch detected: type=%s, category=%r, subcategory=%r not in custom profile.",
                tx_type, category, subcategory
            )
            clarification_needed = True
            confidence = 0.0
            friendly_msg = (
                "Hmm, I couldn't match that transaction to any of your existing budget categories or subcategories. "
                "Please repeat the transaction using an existing category/subcategory, or create the new "
                "category/subcategory in Smerio first and then send the message again."
            )

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
