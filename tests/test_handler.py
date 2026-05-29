import unittest
from unittest.mock import patch, MagicMock
from src import handler, config, payload_utils

class TestHandler(unittest.TestCase):
    def setUp(self):
        self.mock_profile = {
            "base_currency": "USD",
            "categories": {"expense_categories": ["Food"]},
            "accounts": []
        }

    @patch("src.handler.tg.send_message")
    def test_lambda_handler_unauthorized_user(self, mock_send):
        """Verify that lambda_handler completely ignores messages from unauthorized user IDs."""
        event = {
            "body": '{"message": {"from": {"id": 99999999}, "chat": {"id": 12345}, "text": "coffee"}}'
        }
        
        # Override config allowed user
        config.ALLOWED_TELEGRAM_USER_ID = 5139816564
        
        resp = handler.lambda_handler(event, None)
        self.assertEqual(resp["statusCode"], 200)
        mock_send.assert_not_called()

    @patch("boto3.client")
    @patch("src.handler._route_update")
    def test_lambda_handler_authorized_user_self_invoke(self, mock_route, mock_boto):
        """Verify that lambda_handler self-invokes asynchronously for an authorized user ID."""
        event = {
            "body": '{"message": {"from": {"id": 5139816564}, "chat": {"id": 12345}, "text": "coffee"}}'
        }
        config.ALLOWED_TELEGRAM_USER_ID = 5139816564
        
        mock_context = MagicMock()
        mock_context.function_name = "mock_lambda_function"
        
        resp = handler.lambda_handler(event, mock_context)
        self.assertEqual(resp["statusCode"], 200)
        
        # Verify self-invocation call
        mock_boto.assert_called_once_with("lambda")
        mock_boto.return_value.invoke.assert_called_once()
        mock_route.assert_not_called()  # Fast-path does not process synchronously

    @patch("src.handler.smerio_client.get_user_profile")
    @patch("src.handler.parser.get_parser")
    @patch("src.handler.tg.send_message")
    def test_handle_message_success_flow(self, mock_send, mock_get_parser, mock_get_profile):
        """Verify handle_message queries profile, parses with LLM, and sends confirmation with inline buttons."""
        mock_get_profile.return_value = self.mock_profile
        
        mock_parser_instance = MagicMock()
        mock_get_parser.return_value = mock_parser_instance
        mock_parser_instance.parse.return_value = {
            "amount": 20.0,
            "currency": "USD",
            "category": "Food",
            "subcategory": "Cafe",
            "type": "Expense",
            "notes": "coffee",
            "account_id": None,
            "confidence": 0.9,
            "clarification_needed": False,
            "friendly_message": "Yes, I will log $20 for coffee."
        }
        
        message = {
            "from": {"id": 5139816564},
            "chat": {"id": 12345},
            "text": "spent 20$ on coffee"
        }
        
        handler._handle_message(message)
        
        # Check Smerio client and LLM parsing calls
        mock_get_profile.assert_called_once_with(5139816564)
        mock_get_parser.assert_called_once()
        mock_parser_instance.parse.assert_called_once()
        
        # Assert confirmation message was sent with inline buttons
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        self.assertEqual(args[0], 12345)
        self.assertIn("Yes, I will log $20 for coffee.", args[1])
        # Verify invisible zero-width link is included at the beginning
        self.assertTrue(args[1].startswith('<a href="https://smer.io/tx?'))
        self.assertIn("reply_markup", kwargs)
        self.assertEqual(kwargs["reply_markup"]["inline_keyboard"][0][0]["text"], "✅ Yes, log it")
        self.assertEqual(kwargs["reply_markup"]["inline_keyboard"][0][1]["text"], "❌ No, cancel")

    @patch("src.handler.smerio_client.create_transaction")
    @patch("src.handler.tg.answer_callback_query")
    @patch("src.handler.tg.edit_message")
    def test_handle_callback_query_confirm(self, mock_edit, mock_answer, mock_create):
        """Verify confirming a callback query decodes payload statelessly and writes to Smerio."""
        tx_payload = {
            "amount": 20.0,
            "currency": "USD",
            "category": "Food",
            "type": "Expense"
        }
        # Create zero-width html link with this payload
        html_link = payload_utils.encode_payload(tx_payload)
        start_idx = html_link.find('href="') + 6
        end_idx = html_link.find('"', start_idx)
        url = html_link[start_idx:end_idx]
        
        callback_query = {
            "id": "query_1234",
            "data": "confirm",
            "from": {"id": 5139816564},
            "message": {
                "message_id": 98765,
                "chat": {"id": 12345},
                "text": "Yes, I will log $20 for coffee.",
                "entities": [
                    {
                        "type": "text_link",
                        "offset": 0,
                        "length": 1,
                        "url": url
                    }
                ]
            }
        }
        
        handler._handle_callback_query(callback_query)
        
        # Verify transaction logged and answered to Telegram
        mock_create.assert_called_once()
        logged_tx = mock_create.call_args[0][0]
        self.assertEqual(logged_tx["amount"], 20.0)
        self.assertEqual(logged_tx["category"], "Food")
        self.assertEqual(logged_tx["tg_user_id"], "5139816564")
        
        mock_answer.assert_called_once_with("query_1234", "✅ Transaction logged successfully!")
        # Verify message edited to show success and remove buttons
        mock_edit.assert_called_once()
        edit_args, edit_kwargs = mock_edit.call_args
        self.assertEqual(edit_args[0], 12345)
        self.assertEqual(edit_args[1], 98765)
        self.assertIn("Logged successfully!", edit_args[2])
        self.assertEqual(edit_kwargs["reply_markup"], {"inline_keyboard": []})

    @patch("src.handler.tg.answer_callback_query")
    @patch("src.handler.tg.edit_message")
    def test_handle_callback_query_cancel(self, mock_edit, mock_answer):
        """Verify cancelling callback query acts cleanly."""
        callback_query = {
            "id": "query_1234",
            "data": "cancel",
            "from": {"id": 5139816564},
            "message": {
                "message_id": 98765,
                "chat": {"id": 12345},
                "text": "Yes, I will log $20 for coffee."
            }
        }
        
        handler._handle_callback_query(callback_query)
        
        mock_answer.assert_called_once_with("query_1234", "Cancelled")
        mock_edit.assert_called_once()
        self.assertIn("cancelled", mock_edit.call_args[0][2])
