# Smerio Telegram Bot Integration Guide

This document is a technical developer reference for building the separate Telegram Bot project (e.g., hosted on AWS Lambda + API Gateway) that communicates with Smerio. It defines the API contract, request/response JSON schemas, and security handshake protocols.

---

## 1. Security Architecture

To guarantee absolute safety, Smerio enforces a dual-barrier authorization model:
1. **API Token Authorization**: The bot must pass a cryptographically secure random token in the `X-Smerio-Telegram-Token` HTTP header. This token is generated inside the Smerio settings interface.
2. **Immutable Numeric ID Verification**: The bot must specify the sender's Telegram numeric User ID (`tg_user_id`) in every request. Smerio cross-references this with the Smerio database.
   * **Why numeric IDs?** Telegram usernames (e.g. `@john_doe`) are mutable and can be changed, deleted, or spoofed. Unique numeric chat/user IDs are immutable and assigned permanently by Telegram, making them the only secure identifier for financial transactions.

---

## 2. API Reference

All requests must include the secret gateway token in the header:
```http
X-Smerio-Telegram-Token: smerio_tg_your_secret_token_here
```

### 2.1 Fetch Smerio Profile Context

Before parsing transactions, the bot should query the Smerio instance to download the user's custom category list, subcategories list, main currency, and accounts. 
Feeding this lists dynamically into your AI / LLM model's prompt on AWS Lambda guarantees **near 100% classification accuracy**, mapping user inputs directly to their customized budget envelopes and bank cards.

* **Endpoint**: `GET /api/telegram/user`
* **Query Parameters**:
  * `tg_user_id` (string, strictly numeric): The Telegram User ID of the sender (e.g. `123456789`).

#### Success Response (`200 OK`)
```json
{
  "status": "success",
  "username": "Ivan",
  "base_currency": "USD",
  "categories": {
    "expense_categories": [
      "Food",
      "Rent",
      "Transport",
      "Utilities"
    ],
    "expense_subcategories": {
      "Food": [
        "Cafe",
        "Groceries",
        "Delivery"
      ],
      "Transport": [
        "Fuel",
        "Taxi"
      ]
    },
    "income_categories": [
      "Salary",
      "Investments"
    ],
    "income_subcategories": [
      "Salary",
      "Dividends",
      "Freelance"
    ]
  },
  "accounts": [
    {
      "id": "1234567890abcde",
      "name": "Debit Card",
      "currency": "USD"
    },
    {
      "id": "0987654321edcba",
      "name": "Cash Wallet",
      "currency": "EUR"
    }
  ]
}
```

#### Error Responses
* **Missing Header (`401 Unauthorized`)**:
  ```json
  {"status": "error", "message": "Missing X-Smerio-Telegram-Token header"}
  ```
* **Integration Disabled or Token Invalid (`401 Unauthorized`)**:
  ```json
  {"status": "error", "message": "Invalid token or integration disabled"}
  ```
* **User ID Mismatch or non-numeric (`401 Unauthorized`)**:
  ```json
  {"status": "error", "message": "Access Denied: Telegram user ID mismatch"}
  ```

---

### 2.2 Create / Log Transaction

Once the user confirms the parsed transaction inside the Telegram chat, the AWS Lambda bot submits it to Smerio for storage.

* **Endpoint**: `POST /api/telegram/transaction`
* **Headers**:
  * `Content-Type: application/json`
  * `X-Smerio-Telegram-Token: smerio_tg_your_secret_token_here`

#### Request Payload JSON
```json
{
  "tg_user_id": "123456789",
  "amount": 20.00,
  "currency": "USD",
  "category": "Food",
  "subcategory": "Cafe",
  "type": "Expense",
  "notes": "Starbucks 2 cups of coffee",
  "account_id": "1234567890abcde",
  "date": "2026-05-29 14:34:00"
}
```

#### Field Specifications:
* `tg_user_id` (string, required): Immutable numeric Telegram sender ID.
* `amount` (float, required): Positive absolute float amount (e.g. `20.00`).
* `currency` (string, required): 3-letter currency code (e.g., `USD`, `EUR`, `RUB`).
* `category` (string, required): Level 1 Category (Envelope for Expenses, Payee for Income).
* `subcategory` (string, optional): Level 2 Subcategory (Subcategory for Expenses, Source for Income).
* `type` (string, required): Explicit type, must be strictly `'Expense'` or `'Income'`.
* `notes` (string, optional): Details about the purchase.
* `account_id` (string, optional): PocketBase ID of the target account. If omitted, the transaction is logged as an unlinked transaction.
* `date` (string, optional): Transaction timestamp in `YYYY-MM-DD HH:MM:SS` format. If omitted, defaults to the current server time.

#### Backend Handlers & Actions:
1. **Sign Enforcements**: Smerio automatically enforces the correct numeric sign. If `type == 'Expense'`, the amount will be saved in Smerio database as `-20.00`. If `type == 'Income'`, Smerio saves it as `+20.00`.
2. **Currency Conversion**: If the transaction `currency` differs from the Smerio user's `main_currency`, Smerio automatically queries historical cached or external exchange rates to calculate the base equivalent value and writes both base equivalent and original values (`amount_foreign`).
3. **Category Synchronization**: If `category` or `subcategory` does not exist in Smerio yet, Smerio automatically creates them under the resolved user's ownership to prevent transactional relation failures.
4. **Cache Invalidation**: On successful insertion, Smerio immediately invalidates the user's dashboard caches, ensuring the web app visualizes the new metrics instantly.

#### Success Response (`201 Created`)
```json
{
  "status": "success",
  "message": "Transaction logged successfully",
  "transaction_id": "tx_record_id_15chars"
}
```

---

## 3. Recommended AWS Lambda Flow Chart

The typical sequence of operations inside your separate Telegram Bot project when triggered by a Telegram update is as follows:

```
  [Telegram Update Received]
             │
             ▼
  [Verify User ID is Numeric] ──(No)──► [Reply: "Unauthorized Account ID format"]
             │
            (Yes)
             ▼
  [Call Smerio: GET /api/telegram/user]
             │
      ┌──────┴────────────────────────┐
      ▼ (401 Unauthorized)            ▼ (200 OK)
 [Reply: "Integration disabled  [Extract user currency, custom
  or Token Mismatch"]             taxonomy tree & accounts list]
                                      │
                                      ▼
                        [Feed User Text/Photo/Voice
                         + Taxonomy context to LLM]
                                      │
                                      ▼
                        [LLM parses values into Smerio JSON]
                                      │
                                      ▼
                        [Present Inline Button Confirm Panel]
                        "Log $20 Expense in Food -> Cafe? [YES] [NO]"
                                      │
                                      ▼
                        (User taps [YES] button)
                                      │
                                      ▼
                        [Call Smerio: POST /api/telegram/transaction]
                                      │
                               ┌──────┴──────────────────┐
                               ▼ (201 Created)           ▼ (Error 500/400)
                         [Reply: "Logged!"]       [Reply: "Smerio API Error"]
```
