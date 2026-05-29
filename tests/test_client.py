import unittest
from unittest.mock import patch, MagicMock
from src import smerio_client, config

class TestSmerioClient(unittest.TestCase):
    @patch("requests.get")
    def test_get_user_profile_success(self, mock_get):
        """Verify successful retrieval and parsing of Smerio profile."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "username": "Ivan",
            "base_currency": "USD",
            "categories": {"expense_categories": ["Food"]},
            "accounts": []
        }
        mock_get.return_value = mock_response

        profile = smerio_client.get_user_profile(5139816564)
        
        self.assertEqual(profile["username"], "Ivan")
        self.assertEqual(profile["base_currency"], "USD")
        self.assertIn("Food", profile["categories"]["expense_categories"])
        
        # Verify correct headers and params were sent
        mock_get.assert_called_once_with(
            f"{config.SMERIO_API_URL}/api/telegram/user",
            headers={"X-Smerio-Telegram-Token": config.SMERIO_TELEGRAM_TOKEN, "Accept": "application/json"},
            params={"tg_user_id": "5139816564"},
            timeout=10
        )

    @patch("requests.post")
    def test_create_transaction_success(self, mock_post):
        """Verify successful transaction creation payload delivery."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "status": "success",
            "message": "Transaction logged successfully",
            "transaction_id": "tx_record_12345"
        }
        mock_post.return_value = mock_response

        payload = {
            "amount": 20.0,
            "currency": "USD",
            "category": "Food",
            "type": "Expense"
        }
        
        result = smerio_client.create_transaction(payload)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["transaction_id"], "tx_record_12345")
        
        # Verify post payload
        mock_post.assert_called_once_with(
            f"{config.SMERIO_API_URL}/api/telegram/transaction",
            headers={
                "X-Smerio-Telegram-Token": config.SMERIO_TELEGRAM_TOKEN,
                "Accept": "application/json",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=10
        )

    @patch("requests.get")
    def test_get_user_profile_unauthorized(self, mock_get):
        """Verify client raises UnauthorizedError on 401 response."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.text = "Unauthorized Token"
        mock_get.return_value = mock_response

        with self.assertRaises(smerio_client.UnauthorizedError):
            smerio_client.get_user_profile(5139816564)
