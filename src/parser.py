import os
import json
import logging
import requests
from typing import Optional, Tuple, Union
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
  "category": Level 1 category. You MUST strictly select one of the user's custom categories listed in `Expense Categories` (or `Income Categories`) above. You are ABSOLUTELY PROHIBITED from inventing or creating new category names. If no category matches or can be reasonably mapped, you must set `clarification_needed` to true and output a helpful message asking the user to retry or specify the category,
  "subcategory": Level 2 subcategory. You MUST strictly select one of the subcategories from the custom taxonomy lists. You are ABSOLUTELY PROHIBITED from creating or inventing a new subcategory name. Follow these matching rules:
    1. First, search for a semantic or direct match in the subcategories listed under the resolved category inside the custom taxonomy.
    2. If no matching subcategory is found under that specific category, check the global/unassigned subcategories list under the empty string key "" in the `Expense Subcategories (by category)` dictionary (e.g., if user mentions 'groceries' or Russian 'продукты' and the resolved category is 'Food' which only has 'Restaraunt', look under the empty string "" list and match it to 'Продукты').
    3. Perform cross-lingual semantic matching (e.g., user inputs in Russian like 'корм животным' should map to 'Животные', and English 'groceries' should map to 'Продукты' if they are present in the list).
    4. If no subcategory matches or exists anywhere in the custom lists, you are ABSOLUTELY PROHIBITED from inventing one or using standard fallbacks like 'Другое'. Instead, you MUST set `clarification_needed` to true, set `confidence` to a low value (e.g. 0.0), and use `friendly_message` to politely inform the user that the transaction details could not be matched to their existing budget taxonomy and ask them to repeat the operation more clearly or specify the correct category/subcategory. Never output empty string or null when a valid subcategory can be resolved,
  "type": strictly either "Expense" or "Income",
  "notes": very brief notes/details (e.g. merchant name, item description). Keep notes slim as requested! CRITICAL: If a payment method, bank name, or account is mentioned in the user's text (e.g., 'paid via Debit Card', 'using credit card', 'via Cash'), append it to the notes field in parentheses (e.g., 'Starbucks 2 cups of coffee (via Debit Card)'),
  "account_id": pocketbase ID of the matching account from the Smerio accounts list above (e.g., matching 'debit' to a Debit Card account ID). If no account matches or is mentioned, output null,
  "date": the transaction timestamp in "YYYY-MM-DD HH:MM:SS" format. If a relative date is used (e.g. "yesterday at 3pm"), calculate the correct absolute time using the current_time supplied. If no date/time is specified, output null (do NOT guess and do NOT ask for it),
  "confidence": float from 0.0 to 1.0 showing your confidence in the parse,
  "clarification_needed": boolean. Set to true if:
    - The message is completely non-financial (e.g., greetings like 'hello', questions like 'what is my budget?'), OR
    - The transaction amount is completely missing (e.g., 'I bought coffee' with no price), OR
    - The transaction cannot be matched to any of the user's existing categories/subcategories without inventing or creating a new category/subcategory name,
  "friendly_message": A warm, natural, and helpful confirmation reply. 
    - If clarification_needed is false: Confirm the details politely. To prevent any confusion and make it completely clear what Smerio envelopes are being used, you MUST explicitly include and quote the selected category and subcategory using single quotes, formatted as `'Category' -> 'Subcategory'`. Do NOT use generic English descriptive terms (like 'animal feed' or 'grocery purchase') as category or subcategory names.
      * Example: "Got it! I'll record a 2442 RSD expense for animal feed under 'Home & Pets' -> 'Животные' category. Does that look right?"
      * Example: "Got it! I've recorded your grocery purchase of 2000 RSD under the 'Food' -> 'Продукты' category. Is that correct?"
    - If clarification_needed is true because a category/subcategory couldn't be matched: Politely inform the user that you are confused and ask them to repeat the operation more clearly or specify which existing category/subcategory it belongs to.
      * Example: "Hmm, I couldn't match that transaction to any of your existing budget categories or subcategories. Could you please repeat the transaction more clearly or specify the correct category?"
    - If clarification_needed is true because amount is missing or non-financial: Politely ask the user to clarify or supply the missing details. For example: "I see you spent money at Starbucks, but could you please specify how much it cost?"
}}

=== OPERATIONAL LAWS ===
- STRICT CATEGORY & SUBCATEGORY ADHERENCE: You are ABSOLUTELY PROHIBITED from creating, generating, or inventing new category or subcategory names. You MUST strictly select from the existing lists provided in the custom taxonomy. Every category has subcategories, and you must always resolve a valid subcategory from the taxonomy (either from the category-specific list or from the empty string key "" global list). If a transaction cannot be matched without inventing a new name, you MUST set clarification_needed to true and confidence to 0.0, and politely ask the user to clarify or repeat the transaction.
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

    def parse(self, user_message: Optional[str], current_time: str, profile: dict, image_bytes: Optional[bytes] = None) -> dict:
        system_prompt = _build_system_prompt(profile)
        
        parts = []
        if image_bytes:
            import base64
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": b64_data
                }
            })
            
        user_prompt = f"current_time={current_time}\n"
        if user_message:
            user_prompt += f"user_message={user_message}\n"
        user_prompt += "Analyze the receipt/bill image and extract the transaction details according to the custom taxonomy."
        parts.append({"text": user_prompt})

        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{
                "role": "user",
                "parts": parts,
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

    def parse(self, user_message: Optional[str], current_time: str, profile: dict, image_bytes: Optional[bytes] = None) -> dict:
        system_prompt = _build_system_prompt(profile)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        content_parts = []
        if image_bytes:
            import base64
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64_data}"
                }
            })
            
        user_prompt = f"current_time={current_time}\n"
        if user_message:
            user_prompt += f"user_message={user_message}\n"
        user_prompt += "Analyze the receipt/bill image and extract the transaction details according to the custom taxonomy."
        content_parts.append({"type": "text", "text": user_prompt})

        body = {
            "model": config.LLM_MODEL,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content_parts}
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

    def parse(self, user_message: Optional[str], current_time: str, profile: dict, image_bytes: Optional[bytes] = None) -> dict:
        system_prompt = _build_system_prompt(profile)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        content_parts = []
        if image_bytes:
            import base64
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            content_parts.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64_data
                }
            })
            
        user_prompt = f"current_time={current_time}\n"
        if user_message:
            user_prompt += f"user_message={user_message}\n"
        user_prompt += "Analyze the receipt/bill image and extract the transaction details according to the custom taxonomy."
        content_parts.append({"type": "text", "text": user_prompt})
        
        # Guide Claude to strictly output JSON format
        prefill_prompt = "{"
        body = {
            "model": config.LLM_MODEL,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": content_parts},
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
def get_parser() -> Union[GeminiParser, OpenAIParser, ClaudeParser]:
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
