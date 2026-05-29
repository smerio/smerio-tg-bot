import urllib.parse
from typing import Optional

# Zero-width joiner character (invisible in Telegram message but clickable/scannable)
INVISIBLE_CHAR = "\u200d"

# Field mappings to keep the query string as small as possible
FIELD_MAP = {
    "amount": "a",
    "currency": "c",
    "category": "g",
    "subcategory": "s",
    "type": "t",
    "notes": "n",
    "account_id": "ac",
    "date": "d"
}

REVERSE_FIELD_MAP = {v: k for k, v in FIELD_MAP.items()}

def encode_payload(tx: dict) -> str:
    """Encode a transaction dict into an invisible HTML anchor link.
    
    Returns an HTML string like: <a href="https://smer.io/tx?a=20.0&...">&#8205;</a>
    """
    params = {}
    for key, short_key in FIELD_MAP.items():
        val = tx.get(key)
        if val is not None and val != "":
            # Normalize transaction type to single char 'E' or 'I'
            if key == "type":
                if val == "Expense":
                    val = "E"
                elif val == "Income":
                    val = "I"
            params[short_key] = str(val)
            
    query_str = urllib.parse.urlencode(params)
    url = f"https://smer.io/tx?{query_str}"
    
    # Return zero-width link HTML block
    return f'<a href="{url}">{INVISIBLE_CHAR}</a>'

def decode_payload(url: str) -> dict:
    """Decode a smer.io URL back into a full Smerio transaction dictionary."""
    parsed_url = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    
    # Flatten query list parameters
    flat_params = {k: v[0] for k, v in query_params.items() if v}
    
    tx = {}
    for short_key, val in flat_params.items():
        full_key = REVERSE_FIELD_MAP.get(short_key)
        if not full_key:
            continue
            
        if full_key == "amount":
            try:
                tx[full_key] = float(val)
            except ValueError:
                tx[full_key] = 0.0
        elif full_key == "type":
            if val == "E":
                tx[full_key] = "Expense"
            elif val == "I":
                tx[full_key] = "Income"
            else:
                tx[full_key] = val
        else:
            tx[full_key] = val
            
    # Set default values for missing keys
    tx.setdefault("amount", 0.0)
    tx.setdefault("currency", "USD")
    tx.setdefault("category", "Uncategorized")
    tx.setdefault("type", "Expense")
    
    return tx

def extract_payload_from_message(message: dict) -> Optional[dict]:
    """Inspects a Telegram Message object for a hidden zero-width text_link entity.
    
    If found, decodes and returns the transaction dictionary. Otherwise, returns None.
    """
    entities = message.get("entities", [])
    text = message.get("text", "")
    
    for entity in entities:
        if entity.get("type") == "text_link":
            url = entity.get("url", "")
            if url.startswith("https://smer.io/tx?"):
                return decode_payload(url)
                
    # Fallback to caption_entities if it was a photo or media message
    caption_entities = message.get("caption_entities", [])
    for entity in caption_entities:
        if entity.get("type") == "text_link":
            url = entity.get("url", "")
            if url.startswith("https://smer.io/tx?"):
                return decode_payload(url)
                
    return None
