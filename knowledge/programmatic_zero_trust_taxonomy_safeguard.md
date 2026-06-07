# Pattern: Programmatic Zero-Trust Taxonomy Validation Safeguard

This document details the software engineering pattern designed to enforce custom budget taxonomy integrity programmatically within stateless, AI-powered financial assistants. It acts as an ironclad safeguard against LLM hallucinations, ensuring that hallucinated category or subcategory names are never written to the backend database.

---

## 🛑 The Challenge: LLM Hallucinations & Backend Auto-Creation

When a user interacts with a budgeting bot using natural language, we supply the LLM (Gemini, Claude, or OpenAI) with the user's custom budget taxonomy (categories and subcategories) in the system prompt. We instruct the LLM to strictly map transactions to existing envelopes and *prohibit* inventing new names. 

However, LLMs can occasionally suffer from weak prompt adherence or hallucinations (e.g., classifying a physics tutor as `Education -> Education` when `Education` is not present in the user's custom list). 

In serverless or low-maintenance integrations, the budget backend (e.g. Smerio) may dynamically create new categories/subcategories when received in transactional payloads to prevent write failures. This results in **taxonomy pollution**—unwanted envelopes and cards are created automatically in the database due to a single LLM hallucination.

---

## 💡 The Solution: Programmatic Hook Validation

To guarantee absolute taxonomy integrity, we implement a **programmatic safeguard** directly inside the webhook execution flow (`src/handler.py`), immediately following the LLM parsing step.

Instead of trusting the LLM's classification payload, the python code explicitly validates that the suggested category and subcategory exist in the custom Smerio profile taxonomy returned by Smerio's `/api/telegram/user` API.

### Validation Rules Flow

```
   [LLM Returns Parsed JSON]
              │
              ▼
   [Programmatic Taxonomy Check]
              │
    Is Category & Subcategory
      in Custom Profile?
       /              \
     (Yes)            (No)
     /                  \
    ▼                    ▼
[Stateless Confirmation]   [Safeguard Triggered]
- Create zero-width url    - Override 'clarification_needed' = True
- Present [Yes] / [No]      - Set 'confidence' = 0.0
  interactive buttons       - Set friendly confused clarification message
                            - Send message without confirmation buttons
                            - PREVENTS writes to Smerio database!
```

---

## 🛠️ Implementation Details (Python)

### 1. The Programmatic Validator in `handler.py`
Right after parsing, the handler verifies the LLM-returned fields against the profile context before constructing the confirmation buttons:

```python
    # Programmatic Zero-Trust Taxonomy Validation Safeguard
    if not clarification_needed:
        category = parsed_tx.get("category")
        subcategory = parsed_tx.get("subcategory")
        tx_type = parsed_tx.get("type", "Expense")
        
        categories_ctx = profile.get("categories", {})
        
        valid = True
        if tx_type == "Expense":
            expense_categories = categories_ctx.get("expense_categories", [])
            if category not in expense_categories:
                valid = False
            
            if valid and subcategory:
                expense_subcategories = categories_ctx.get("expense_subcategories", {})
                specific_subs = expense_subcategories.get(category, [])
                global_subs = expense_subcategories.get("", [])
                if subcategory not in specific_subs and subcategory not in global_subs:
                    valid = False
                    
        elif tx_type == "Income":
            income_categories = categories_ctx.get("income_categories", [])
            if category not in income_categories:
                valid = False
                
            if valid and subcategory:
                income_subcategories = categories_ctx.get("income_subcategories", [])
                if subcategory not in income_subcategories:
                    valid = False
        else:
            valid = False
            
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
```

---

## ⚡ Benefits & Safeguards

* **Zero Taxonomy Pollution**: Programmatically blocks the creation of unwanted database envelopes, keeping the user's categories clean.
* **Resilient to Hallucinations**: Standardizes security by separating the AI logic (parsing and translation) from authorization/business constraints (strictly allowed lists).
* **Graceful Degradation**: Leverages the existing stateless clarification trigger. If a mismatch is programmatically identified, the buttons disappear, and the user receives a helpful, context-appropriate message requesting clarification.
