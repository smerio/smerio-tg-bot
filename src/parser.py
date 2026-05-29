import os
import json
import logging
import requests
from typing import Optional, Tuple
import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are the AI parser inside Ivan's personal finance bot for Smerio.
Your job is to parse a free-form transaction message from the user and match it against their custom Smerio profile context.

=== SMERIO CUSTOM TAXONOMY & ACCOUNTS ===
Base Currency: {base_currency}
Expense Categories: {expense_categories}
Expense Subcategories (by category): {expense_subcategories}
Income Categories: {income_categories}
Income Subcategories: {income_subcategories}
Accounts (Available budget envelopes/bank cards): {accounts}

=== SCHEMAS & CLASSIFICATION RULES ===
You must return a JSON object with the following fields:
{{
  "amount": positive float representing the transaction cost or proceed,
  "currency": 3-letter currency code (e.g. "USD", "EUR", "RUB"). If not specified, default to the user's base currency: {base_currency},
  "category": Level 1 category. Try your best to match one of the user's custom categories listed above. If no match is found, assign a logical, clean category name,
  "subcategory": Level 2 subcategory. Try to match the subcategories under the resolved category. If no subcategories match or exist, use a clean, logical name or null,
  "type": strictly either "Expense" or "Income",
  "notes": very brief notes/details (e.g. merchant name, item description). Keep notes slim as requested! CRITICAL: If a payment method, bank name, or account is mentioned in the user's text (e.g., 'paid via Debit Card', 'using credit card', 'via Cash'), append it to the notes field in parentheses (e.g., 'Starbucks 2 cups of coffee (via Debit Card)'),
  "account_id": pocketbase ID of the matching account from the Smerio accounts list above (e.g., matching 'debit' to a Debit Card account ID). If no account matches or is mentioned, output null,
  "date": the transaction timestamp in "YYYY-MM-DD HH:MM:SS" format. If a relative date is used (e.g. "yesterday at 3pm"), calculate the correct absolute time using the current_time supplied. If no date/time is specified, output null (do NOT guess and do NOT ask for it),
  "confidence": float from 0.0 to 1.0 showing your confidence in the parse,
  "clarification_needed": boolean. Set to true ONLY if the message is completely non-financial (e.g., greetings like 'hello', questions like 'what is my budget?'), or if the transaction amount is completely missing (e.g., 'I bought coffee' with no price). If an amount is present, set clarification_needed to false and do NOT ask for details,
  "friendly_message": A warm, natural, and helpful confirmation reply. 
    - If clarification_needed is false: Confirm the details politely. For example: "Yes, I am glad that you had 2 cups of coffee, I will add this as transaction - category Food, subcategory Cafe, amount 20, currency usd, is it right?"
    - If clarification_needed is true: Politley ask the user to clarify or supply the missing details. For example: "I see you spent money at Starbucks, but could you please specify how much it cost?"
}}

=== OPERATIONAL LAWS ===
- NEVER ask clarifying questions or require user inputs for missing accounts, payment cards, or dates/times if an amount is present. Proceed with high confidence and let the Smerio app handle backend defaults.
- Truncate and clean notes. Keep them very concise.
- Output ONLY the raw JSON block. Do NOT surround in markdown code blocks like ```json ... ```. No conversational prose outside the JSON.
"""

def _build_system_prompt(profile: dict) -> str:
    """Inject user-specific Smerio categories and accounts into the parser system prompt."""
    categories = profile.get("categories", {})
    expense_categories = categories.get("expense_categories", [])
    expense_subcategories = categories.get("expense_subcategories", {})
    income_categories = categories.get("income_categories", [])
    income_subcategories = categories.get("income_subcategories", [])
    base_currency = profile.get("base_currency", "USD")
    
    # Format accounts into a concise list of names and IDs
    accounts = []
    for acc in profile.get("accounts", []):
        accounts.append({
            "id": acc.get("id"),
            "name": acc.get("name"),
            "currency": acc.get("currency")
        })
        
    return SYSTEM_PROMPT_TEMPLATE.format(
        base_currency=base_currency,
        expense_categories=json.dumps(expense_categories),
        expense_subcategories=json.dumps(expense_subcategories),
        income_categories=json.dumps(income_categories),
        income_subcategories=json.dumps(income_subcategories),
        accounts=json.dumps(accounts)
    )

class LLMParserError(Exception):
    """Raised when the LLM parser fails to retrieve or parse transaction."""

# ---------------------------------------------------------------------------
# Gemini Parser (REST REST direct call)
# ---------------------------------------------------------------------------
class GeminiParser:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.LLM_MODEL}:generateContent"

    def parse(self, user_message: str, current_time: str, profile: dict) -> dict:
        system_prompt = _build_system_prompt(profile)
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{
                "role": "user",
                "parts": [{"text": f"current_time={current_time}\nuser_message={user_message}"}],
            }],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        try:
            resp = requests.post(self.url, params={"key": self.api_key}, json=body, timeout=15)
            if not resp.ok:
                raise LLMParserError(f"Gemini API returned status {resp.status_code}: {resp.text}")
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text.strip())
        except Exception as e:
            logger.exception("Gemini parse failure")
            raise LLMParserError(f"Failed to parse with Gemini: {e}") from e

# ---------------------------------------------------------------------------
# OpenAI Parser (REST direct call)
# ---------------------------------------------------------------------------
class OpenAIParser:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://api.openai.com/v1/chat/completions"

    def parse(self, user_message: str, current_time: str, profile: dict) -> dict:
        system_prompt = _build_system_prompt(profile)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        body = {
            "model": config.LLM_MODEL,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"current_time={current_time}\nuser_message={user_message}"}
            ]
        }
        try:
            resp = requests.post(self.url, headers=headers, json=body, timeout=15)
            if not resp.ok:
                raise LLMParserError(f"OpenAI API returned status {resp.status_code}: {resp.text}")
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return json.loads(text.strip())
        except Exception as e:
            logger.exception("OpenAI parse failure")
            raise LLMParserError(f"Failed to parse with OpenAI: {e}") from e

# ---------------------------------------------------------------------------
# Claude Parser (REST direct call)
# ---------------------------------------------------------------------------
class ClaudeParser:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://api.anthropic.com/v1/messages"

    def parse(self, user_message: str, current_time: str, profile: dict) -> dict:
        system_prompt = _build_system_prompt(profile)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        # Guide Claude to strictly output JSON format
        prefill_prompt = "{"
        body = {
            "model": config.LLM_MODEL,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": f"current_time={current_time}\nuser_message={user_message}"},
                {"role": "assistant", "content": prefill_prompt}
            ]
        }
        try:
            resp = requests.post(self.url, headers=headers, json=body, timeout=15)
            if not resp.ok:
                raise LLMParserError(f"Claude API returned status {resp.status_code}: {resp.text}")
            data = resp.json()
            text = prefill_prompt + data["content"][0]["text"]
            return json.loads(text.strip())
        except Exception as e:
            logger.exception("Claude parse failure")
            raise LLMParserError(f"Failed to parse with Claude: {e}") from e

# ---------------------------------------------------------------------------
# LLM Parser Factory
# ---------------------------------------------------------------------------
def get_parser() -> GeminiParser | OpenAIParser | ClaudeParser:
    provider = config.LLM_PROVIDER
    key = config.LLM_API_KEY
    
    if provider == "gemini":
        return GeminiParser(key)
    elif provider == "openai":
        return OpenAIParser(key)
    elif provider == "claude":
        return ClaudeParser(key)
    else:
        raise ValueError(f"Invalid LLM_PROVIDER: {provider!r}")
