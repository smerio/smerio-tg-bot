import unittest
from unittest.mock import patch, MagicMock
from src import parser

class TestParser(unittest.TestCase):
    def setUp(self):
        self.mock_profile = {
            "base_currency": "USD",
            "categories": {
                "expense_categories": ["Food", "Transport"],
                "expense_subcategories": {
                    "Food": ["Cafe", "Groceries"],
                    "Transport": ["Taxi"]
                },
                "income_categories": ["Salary"],
                "income_subcategories": ["Bonus"]
            },
            "accounts": [
                {"id": "acc_1", "name": "Debit Card", "currency": "USD"},
                {"id": "acc_2", "name": "Cash Wallet", "currency": "EUR"}
            ]
        }

    def test_build_system_prompt(self):
        """Verify Smerio context is correctly injected into the prompt template."""
        prompt = parser._build_system_prompt(self.mock_profile)
        self.assertIn("USD", prompt)
        self.assertIn("Expense Categories:", prompt)
        self.assertIn("Food", prompt)
        self.assertIn("acc_1", prompt)
        self.assertIn("Debit Card", prompt)

    @patch("requests.post")
    def test_gemini_parser_success(self, mock_post):
        """Verify GeminiParser handles a successful API response and parses payload."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"amount": 20.0, "currency": "USD", "category": "Food", "subcategory": "Cafe", "type": "Expense", "notes": "coffee", "account_id": "acc_1", "clarification_needed": false, "friendly_message": "Log expense?"}'
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        gemini = parser.GeminiParser(api_key="mock_key")
        result = gemini.parse(
            user_message="spent 20$ on coffee", 
            current_time="2026-05-29 15:00:00", 
            profile=self.mock_profile
        )

        self.assertEqual(result["amount"], 20.0)
        self.assertEqual(result["category"], "Food")
        self.assertEqual(result["subcategory"], "Cafe")
        self.assertEqual(result["account_id"], "acc_1")
        self.assertFalse(result["clarification_needed"])
        self.assertEqual(result["friendly_message"], "Log expense?")
