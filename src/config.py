import os

# Load .env file for local runs if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_ID = os.environ.get("BOT_ID", "smerio_bot")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing mandatory environment variable: TELEGRAM_BOT_TOKEN")

SMERIO_API_URL = os.environ.get("SMERIO_API_URL")
if not SMERIO_API_URL:
    raise ValueError("Missing mandatory environment variable: SMERIO_API_URL")
# Strip trailing slash from Smerio URL if present
SMERIO_API_URL = SMERIO_API_URL.rstrip("/")

SMERIO_TELEGRAM_TOKEN = os.environ.get("SMERIO_TELEGRAM_TOKEN")
if not SMERIO_TELEGRAM_TOKEN:
    raise ValueError("Missing mandatory environment variable: SMERIO_TELEGRAM_TOKEN")

ALLOWED_USER_RAW = os.environ.get("ALLOWED_TELEGRAM_USER_ID")
if not ALLOWED_USER_RAW:
    raise ValueError("Missing mandatory environment variable: ALLOWED_TELEGRAM_USER_ID")

try:
    ALLOWED_TELEGRAM_USER_ID = int(ALLOWED_USER_RAW)
except ValueError as e:
    raise ValueError(f"ALLOWED_TELEGRAM_USER_ID must be a numeric integer, got: {ALLOWED_USER_RAW!r}") from e

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()
if LLM_PROVIDER not in ("gemini", "claude", "openai"):
    raise ValueError(f"Unsupported LLM_PROVIDER: {LLM_PROVIDER!r}. Supported: 'gemini', 'claude', 'openai'")

LLM_API_KEY = os.environ.get("LLM_API_KEY")
if not LLM_API_KEY:
    raise ValueError("Missing mandatory environment variable: LLM_API_KEY")
