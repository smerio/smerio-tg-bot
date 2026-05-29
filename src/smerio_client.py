import requests
from typing import Union
import config

class SmerioClientError(Exception):
    """Base exception for Smerio API errors."""

class UnauthorizedError(SmerioClientError):
    """Raised on 401 Unauthorized errors."""

class UserNotFoundError(SmerioClientError):
    """Raised when the Telegram user ID is not registered or linked."""

def _get_headers() -> dict:
    return {
        "X-Smerio-Telegram-Token": config.SMERIO_TELEGRAM_TOKEN,
        "Accept": "application/json"
    }

def get_user_profile(tg_user_id: Union[int, str]) -> dict:
    """Fetch Smerio profile context: categories, base currency, accounts.
    
    Endpoint: GET /api/telegram/user
    Query parameter: tg_user_id
    """
    url = f"{config.SMERIO_API_URL}/api/telegram/user"
    params = {"tg_user_id": str(tg_user_id)}
    
    try:
        resp = requests.get(url, headers=_get_headers(), params=params, timeout=10)
    except requests.RequestException as e:
        raise SmerioClientError(f"Network error calling Smerio: {e}") from e
        
    if resp.status_code == 401:
        raise UnauthorizedError(f"Access Denied: Invalid Smerio token or unregistered Telegram ID: {resp.text}")
    elif resp.status_code == 404:
        raise UserNotFoundError("User not found or Telegram integration not set up in Smerio settings.")
    elif not resp.ok:
        raise SmerioClientError(f"Smerio API returned status {resp.status_code}: {resp.text}")
        
    try:
        data = resp.json()
    except ValueError as e:
        raise SmerioClientError("Failed to parse Smerio JSON response") from e
        
    if data.get("status") == "error":
        raise SmerioClientError(data.get("message", "Unknown Smerio error"))
        
    return data

def create_transaction(payload: dict) -> dict:
    """Submit a validated transaction to Smerio.
    
    Endpoint: POST /api/telegram/transaction
    Payload JSON fields:
      - tg_user_id (string, required)
      - amount (float, required)
      - currency (string, required)
      - category (string, required)
      - subcategory (string, optional)
      - type (string, strictly 'Expense' or 'Income', required)
      - notes (string, optional)
      - account_id (string, optional)
      - date (string, format 'YYYY-MM-DD HH:MM:SS', optional)
    """
    url = f"{config.SMERIO_API_URL}/api/telegram/transaction"
    headers = _get_headers()
    headers["Content-Type"] = "application/json"
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
    except requests.RequestException as e:
        raise SmerioClientError(f"Network error calling Smerio: {e}") from e
        
    if resp.status_code == 401:
        raise UnauthorizedError(f"Access Denied: Invalid Smerio token or unauthorized user ID: {resp.text}")
    elif not resp.ok:
        raise SmerioClientError(f"Smerio API returned status {resp.status_code}: {resp.text}")
        
    try:
        data = resp.json()
    except ValueError as e:
        raise SmerioClientError("Failed to parse Smerio JSON response") from e
        
    if data.get("status") == "error":
        raise SmerioClientError(data.get("message", "Unknown Smerio error"))
        
    return data
