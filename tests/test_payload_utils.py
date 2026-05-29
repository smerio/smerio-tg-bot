import unittest
from src import payload_utils

class TestPayloadUtils(unittest.TestCase):
    def setUp(self):
        self.sample_tx = {
            "amount": 20.0,
            "currency": "USD",
            "category": "Food",
            "subcategory": "Cafe",
            "type": "Expense",
            "notes": "Starbucks 2 cups of coffee",
            "account_id": "1234567890abcde",
            "date": "2026-05-29 14:34:00"
        }

    def test_encode_and_decode_symmetry(self):
        """Verify that encoding a transaction and then decoding it preserves all properties."""
        html_link = payload_utils.encode_payload(self.sample_tx)
        
        # HTML anchor parsing to extract URL
        # Anchor structure: <a href="URL">invisible_char</a>
        start_idx = html_link.find('href="') + 6
        end_idx = html_link.find('"', start_idx)
        url = html_link[start_idx:end_idx]
        
        decoded_tx = payload_utils.decode_payload(url)
        
        self.assertEqual(decoded_tx["amount"], self.sample_tx["amount"])
        self.assertEqual(decoded_tx["currency"], self.sample_tx["currency"])
        self.assertEqual(decoded_tx["category"], self.sample_tx["category"])
        self.assertEqual(decoded_tx["subcategory"], self.sample_tx["subcategory"])
        self.assertEqual(decoded_tx["type"], self.sample_tx["type"])
        self.assertEqual(decoded_tx["notes"], self.sample_tx["notes"])
        self.assertEqual(decoded_tx["account_id"], self.sample_tx["account_id"])
        self.assertEqual(decoded_tx["date"], self.sample_tx["date"])

    def test_extract_payload_from_message(self):
        """Verify that extracting the payload from a Telegram message works via entities."""
        html_link = payload_utils.encode_payload(self.sample_tx)
        
        # Extract URL for mock message entity
        start_idx = html_link.find('href="') + 6
        end_idx = html_link.find('"', start_idx)
        url = html_link[start_idx:end_idx]
        
        mock_message = {
            "text": f"\u200dHey, I parsed your transaction",
            "entities": [
                {
                    "type": "text_link",
                    "offset": 0,
                    "length": 1,
                    "url": url
                }
            ]
        }
        
        extracted_tx = payload_utils.extract_payload_from_message(mock_message)
        self.assertIsNotNone(extracted_tx)
        self.assertEqual(extracted_tx["amount"], 20.0)
        self.assertEqual(extracted_tx["category"], "Food")
        self.assertEqual(extracted_tx["subcategory"], "Cafe")
        self.assertEqual(extracted_tx["notes"], "Starbucks 2 cups of coffee")

    def test_decode_missing_fields_defaults(self):
        """Verify that missing fields get clean defaults upon decoding."""
        url = "https://smer.io/tx?a=5.0&c=EUR"
        decoded = payload_utils.decode_payload(url)
        
        self.assertEqual(decoded["amount"], 5.0)
        self.assertEqual(decoded["currency"], "EUR")
        self.assertEqual(decoded["category"], "Uncategorized")
        self.assertEqual(decoded["type"], "Expense")
        self.assertIsNone(decoded.get("subcategory"))
        self.assertIsNone(decoded.get("notes"))
