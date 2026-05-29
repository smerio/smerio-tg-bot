# Pattern: Strict Custom Taxonomy Matching & Clarification Trigger

This document details the engineering and prompt pattern established to enforce strict custom budget taxonomy mapping in AI-powered financial assistants. It ensures that the AI cannot invent new category or subcategory names, correctly resolves global unassigned subcategories, and handles taxonomy mismatches by gracefully triggering user clarifications.

---

## 🛑 The Challenge: Taxonomy Invention and Mismatches

When users interface with a budgeting bot via free-form text or receipt photos, standard LLM classification poses two major challenges:
1. **Ad-hoc Generation**: The AI might generate a logical but non-existent category or subcategory name (e.g. creating `groceries` as a subcategory instead of mapping to the user's existing Russian subcategory `"Продукты"`).
2. **Taxonomy Pollution**: If the backend dynamically synchronizes unknown categories, this leads to duplicate envelopes or a messy taxonomy.
3. **Mismatches**: When no logically close category or subcategory matches, assigning an arbitrary fallback (like `"Другое"` or `"Other"`) pollutes transaction categorization without the user's explicit intent.

---

## 💡 The Solution: Strict Non-Creation & Clarification Flow

To address these challenges, the system prompt and parser logic are designed with three core concepts:

### 1. Zero-Width Link Stateless Confirmation with Single Quotes
When confirming details in the Telegram chat card, the matched category and subcategory must be wrapped in single quotes in `'Category' -> 'Subcategory'` format.
* *Standardizing*: Instead of saying *"I'll log your grocery purchase under Food category"*, the bot replies with *"I've recorded your grocery purchase under the 'Food' -> 'Продукты' category."*
* *User Control*: The single quotes make it explicit to the user exactly what envelopes in their budget are being selected, preventing accidental writes.

### 2. Global Unassigned Subcategory Matcher (The `""` key)
The Smerio category profile context separates subcategories into category-specific sets and a global, unassigned list located under the empty string key `""`.
* **Resolution Rule**: The parser first checks if the subcategory matches a list item under the resolved category (e.g., matching a restaurant to `Food -> Restaraunt`).
* **Global Fallback**: If no direct category set matches, the LLM searches the global unassigned list under the `""` key (e.g., matching `"groceries"` to the `"Продукты"` subcategory under the `"Food"` category).
* **Cross-Lingual Semantic Matching**: Instructs the LLM to map concepts seamlessly between languages (e.g., mapping `"animal feed"` to `"Животные"` and `"groceries"` to `"Продукты"`).

### 3. Confused Clarification Trigger
If a transaction details cannot be mapped to the existing taxonomy without inventing a new name, the AI must not generate a new name or fallback. Instead, it must trigger the clarification flow:
* **LLM Output**: Set `clarification_needed: true` and `confidence: 0.0`.
* **Polite Clarification Request**: The `friendly_message` must explicitly inform the user that it could not match the transaction to their existing taxonomy, and ask them to repeat the transaction more clearly or specify the category:
  > *"Hmm, I couldn't match that transaction to any of your existing budget categories or subcategories. Could you please repeat the transaction more clearly or specify the correct category?"*
* **Stateless Safeguard**: The Telegram webhook webhook drops the confirmation panel (removing `[Yes, log it]` / `[No, cancel]` inline buttons) and simply displays the clarification request, preventing any invalid writes to the Smerio database.

---

## 🛠️ Prompts & Operational Laws (Python)

### Parser Field Guidelines
```json
{
  "category": "Level 1 category. You MUST strictly select one of the user's custom categories listed in `Expense Categories` (or `Income Categories`) above. You are ABSOLUTELY PROHIBITED from inventing or creating new category names. If no category matches or can be reasonably mapped, you must set `clarification_needed` to true and output a helpful message asking the user to retry or specify the category.",
  "subcategory": "Level 2 subcategory. You MUST strictly select one of the subcategories from the custom taxonomy lists. You are ABSOLUTELY PROHIBITED from creating or inventing a new subcategory name. Follow these matching rules: (1) Check category subcategory list, (2) Check unassigned list under empty key \"\", (3) Cross-lingual matching, (4) If no match exists, set clarification_needed to true and confidence to 0.0.",
  "clarification_needed": "boolean. Set to true if amount is missing, if it is non-financial, or if the transaction cannot be matched to existing taxonomy without creating a new item."
}
```

### Prompt Operational Law
```text
- STRICT CATEGORY & SUBCATEGORY ADHERENCE: You are ABSOLUTELY PROHIBITED from creating, generating, or inventing new category or subcategory names. You MUST strictly select from the existing lists provided in the custom taxonomy. Every category has subcategories, and you must always resolve a valid subcategory from the taxonomy. If a transaction cannot be matched without inventing a new name, you MUST set clarification_needed to true and confidence to 0.0, and politely ask the user to clarify or repeat the transaction.
```
