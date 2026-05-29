# Smerio Telegram Bot Integration Memory

This file serves as the system's memory for the **Smerio Telegram Bot Integration** project. It details the system goals, active architecture, historic development progress, dynamic updates, and key future steps.

---

## 🎯 Project Overview & Objective
The goal is to create a secure, completely stateless, production-ready Telegram Bot integration for **Smerio** (a standalone personal budgeting application).
The bot allows a single authorized user to:
1. **Log Free-Format Text Transactions**: e.g., *"spent 20$ on 2 cups of coffee in starbucks"* logs $20 under Food > Cafe with notes *"Starbucks 2 cups of coffee"*.
2. **Log Receipt Photos**: Send a photo of a receipt or bill for multimodal AI parsing (OCR, exact categorization, currency, and value extraction).
3. **Stateless Interactive Confirmation**: Instantly respond with a structured panel card showing the parsed details and interactive inline buttons (`[✅ Yes, log it]` and `[❌ No, cancel]`) without using any database or state storage in AWS.

---

## 🏗️ Architectural Core: Option C (Stateless Webhook)
To maintain an operating footprint of **absolute zero cost ($0.00)** and eliminate database maintenance overhead, the bot employs a state-of-the-art stateless interactive design:
* **The Challenge**: Telegram callback inline query payloads (`callback_data`) are strictly capped at **64 bytes**, preventing us from encoding parsed transaction dictionaries directly in button callbacks.
* **The Solution**: 
  1. The parsed transaction fields are serialized into compact URI query parameters.
  2. These parameters are embedded as a hidden, zero-width clickable URL anchor (`\u200d`) prepended to the confirmation message.
  3. When the user taps **[Yes, log it]**, the webhook intercepts the callback query, extracts the zero-width metadata from the message entities, decodes it back to JSON, posts it to Smerio, and edits the message to show a success status in real-time.
  4. This eliminates the need for DynamoDB, Redis, or local database caches completely.

---

## 🛠️ Key Progress & System Updates (Today's Session)

1. **Multimodal Receipt Processing (OCR & Multi-provider APIs)**:
   * Added full support for receipt and invoice photo processing.
   * Intercepts photo payloads, retrieves file details via Telegram's `getFile`, downloads in-memory, converts to base64, and runs multimodal LLM analysis.
   * Integrated unified lightweight API wrappers for **Gemini** (default `gemini-2.0-flash`), **Claude** (`claude-3-5-haiku` / `claude-haiku-4-5-20251001`), and **OpenAI** (`gpt-4o-mini`).

2. **Model 404 Error Remediation**:
   * Addressed Claude 404 errors by fully parameterizing model definitions in `config.py` and resolving them with dynamic fallbacks to active, validated model tags (`claude-haiku-4-5-20251001`).

3. **Single-Turn Interaction & Strict Confirmation Mapping**:
   * Removed interactive questions asking for payment sources/accounts or transaction dates (to prevent context leaks since the app is completely database-free).
   * Forced the system prompt to immediately output confirmation cards upon transaction details being provided, defaulting dates to current local time and appending extra payment methods/card details inside parenthesis in the `notes` field.

4. **Zero-Trust Security & Parameterization**:
   * Implemented strict numeric Telegram User ID checking to drop unauthorized updates instantly.
   * Parameterized all AWS resources under a customizable `bot_id` prefix in Terraform.
   * **Side-by-Side Isolated Multi-State Deployments**: Isolated individual bot environments using separate config variables (`ivan.tfvars` vs `olga.tfvars`) and separate state files (`ivan.tfstate` vs `olga.tfstate`) in Terraform to support deploying both bots in the same AWS account without resource collision.

5. **GitHub Integration & Release Publishing**:
   * Initialized Git repository remote tracking, successfully pushed code and version release tags (`v1.0.0` - `v1.3.0`) over HTTPS to [github.com/smerio/smerio-tg-bot](https://github.com/smerio/smerio-tg-bot).
   * Created official GitHub Release **`v1.3.0 - Multimodal Receipt Parsing Support`** containing the latest updates.

---

## 🚀 Future Maintenance Commands
To prevent resource collisions in AWS, manage each bot explicitly by specifying its own state file and variables:

* **Manage Ivan's Bot**:
  ```bash
  terraform apply -state=ivan.tfstate -var-file=ivan.tfvars
  ```
* **Manage Olga's Bot**:
  ```bash
  terraform apply -state=olga.tfstate -var-file=olga.tfvars
  ```

---

## 📅 Next Steps
1. **Webhook Registration**: Complete the webhook registration for Ivan's bot by executing the custom `curl` command with the newly generated `v1.3.1` release configuration parameters.
2. **Side-by-Side Validation**: Test both bots concurrently to ensure stateless parsed responses remain isolated and correct.
3. **Local Testing Setup**: Resolve the Python version incompatibility (typings for Python 3.9) inside `tests/` if local unit tests need to run in the local Pyenv environment.
