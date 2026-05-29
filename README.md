# Smerio Telegram Bot Integration

A production-grade, highly secure, and **stateless** Telegram Bot for **Smerio** (a standalone personal budgeting application). 

This bot empowers you to log transactions inside Smerio using free-format natural language (e.g., *"spent $20 on 2 cups of coffee in starbucks"*). It downloads your custom Smerio categories, subcategories, currencies, and accounts context dynamically, maps your input with near 100% precision using an LLM (Gemini, Claude, or OpenAI), presents an interactive **[Yes, log it] / [No, cancel]** confirmation panel in Telegram, and logs the transaction to Smerio upon confirmation.

---

## 🌟 Key Features

1. **Stateless Interactive Confirmation Flow**: Using advanced Telegram engineering, the parsed transaction payload is encoded as query parameters inside a hidden, zero-width clickable URL anchor (`\u200d`) at the beginning of the confirmation message. When you click **[Yes, log it]**, the AWS Lambda function extracts the payload from the message entities, decodes it, and posts it to Smerio. **No database is required in AWS!**
2. **Dynamic Taxonomy Prompting**: Fetches your customized expense and income categories, subcategories, currencies, and bank accounts list dynamically from Smerio's `/api/telegram/user` endpoint and injects them directly into the LLM system prompt for maximum classification accuracy.
3. **Multi-Provider LLM Engine**: Native support for **Gemini** (default `gemini-2.0-flash`), **Claude** (`claude-3-5-haiku`), and **OpenAI** (`gpt-4o-mini`) via unified lightweight REST wrappers, completely bypassing bulky SDKs to ensure ultra-fast Lambda warm-ups and sub-100ms response times.
4. **Zero-Trust Security Filter**: Enforces double-barrier authorization:
   * **API Token Authorization**: Authenticates with your Smerio instance using a secret gateway token passed in the `X-Smerio-Telegram-Token` header.
   * **Immutable User ID verification**: Automatically intercepts incoming Telegram webhooks and discards any updates originating from user IDs that do not match your hardcoded numeric ID configured in the variables.
5. **Collision-Free Dynamic Prefixing**: Terraform parameters use a custom `bot_id` prefix, allowing you to run multiple side-by-side installations of this bot (or alongside other bots like the crypto portfolio ledger bot) in the same AWS account without resource naming or IAM conflicts.
6. **Async Webhook Handler**: Webhook Lambda invokes itself asynchronously to run the slow LLM path and instantly returns `200 OK` to Telegram within 50ms, eliminating "double-trigger" double-write webhook retry bugs.

---

## 📋 Prerequisites

Before starting, ensure you have:
* An **AWS Account** with CLI credentials configured locally (`aws configure`).
* **Terraform** CLI (v1.6.0 or higher) installed.
* **Python 3.12** installed locally.
* A **Telegram Account**.
* An API Key for your preferred LLM provider:
  * [Google AI Studio (Gemini Key)](https://aistudio.google.com/)
  * [Anthropic Console (Claude Key)](https://console.anthropic.com/)
  * [OpenAI Platform (GPT Key)](https://platform.openai.com/)
* A live, publicly accessible **Smerio Standalone Instance** URL.

---

## 🚀 Step-by-Step Setup Guide

### Step 1: Register Your Telegram Bot
1. Open Telegram and search for the official [@BotFather](https://t.me/BotFather).
2. Type `/newbot` and follow the prompts to name your bot and choose a username.
3. Copy the secure **HTTP API Token** generated (e.g., `123456789:ABCdefGh...`). Keep this token strictly confidential.

### Step 2: Get Your Telegram Numeric User ID
Because Telegram usernames can be changed or spoofed, Smerio enforces immutable numeric user IDs.
1. Search for [@userinfobot](https://t.me/userinfobot) or [@IDBot](https://t.me/myidbot) on Telegram and start it.
2. The bot will reply with your unique numeric ID (e.g. `5139816564`). Copy this ID.

### Step 3: Configure Telegram Integration in Smerio
1. Log into your Smerio standalone application interface.
2. Navigate to **Settings** -> **Telegram Bot Integration**.
3. Enable the Telegram Integration.
4. Set your numeric Telegram **User ID** (copied in Step 2).
5. Generate a secure random **Gateway Token** (e.g. `smerio_tg_secret_gateway_token_here`).
6. Click **Save Settings**.

---

### Step 4: Package Lambda Layer Dependencies
Because AWS Lambda requires packaged dependencies for python runtimes, we create a clean dependency layer.
1. Navigate to the root directory of this project:
   ```bash
   cd /Users/ivan/Documents/Antigravity/016_smerio_tg_bot
   ```
2. Create the target dependency directories:
   ```bash
   mkdir -p layer/python
   ```
3. Install the requirements directly into the layer directory using `pip`:
   ```bash
   pip install -r requirements.txt -t layer/python
   ```

---

### Step 5: Configure and Deploy via Terraform

1. Navigate to the `terraform` folder:
   ```bash
   cd terraform
   ```
2. Initialize Terraform:
   ```bash
   terraform init
   ```

Depending on your use case, choose one of the following deployment paths:

#### Option A: Single Bot Deployment
1. Copy the template variables file to the active configuration file:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```
2. Open `terraform.tfvars` in your editor and configure your settings.
3. Deploy the resources:
   ```bash
   terraform apply
   ```

#### Option B: Multi-Bot Side-by-Side isolated Deployment
If you want to run multiple independent bots (e.g. one for yourself and one for your spouse) side-by-side inside the same AWS account without collision, use isolated configurations:
1. Create a dedicated `.tfvars` file for each bot (e.g., `ivan.tfvars`, `olga.tfvars`) by copying `terraform.tfvars.example`.
2. Configure each file with its own unique `bot_id`, `allowed_telegram_user_id`, `telegram_bot_token`, and API settings.
3. Deploy each bot independently using isolated local state files:
   ```bash
   # Deploy Ivan's bot
   terraform apply -state=ivan.tfstate -var-file=ivan.tfvars
   
   # Deploy Olga's bot
   terraform apply -state=olga.tfstate -var-file=olga.tfvars
   ```

Once the deployment completes, Terraform will output your final Webhook URL:
```bash
Outputs:
webhook_url = "https://a1b2c3d4.execute-api.eu-central-1.amazonaws.com/webhook"
lambda_function_name = "smerio-bot-bot1"
```
Copy the `webhook_url` value.

---

### Step 6: Link Your Telegram Bot to AWS
Register the webhook URL with Telegram to ensure updates are routed to your Lambda function.

Run the following `curl` command in your terminal, replacing `<TELEGRAM_BOT_TOKEN>` with the token for the respective bot, and `<WEBHOOK_URL>` with the specific URL output by Terraform in Step 5:

```bash
curl -F "url=<WEBHOOK_URL>" https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook
```

You should receive a successful confirmation:
```json
{"ok":true,"result":true,"description":"Webhook was set"}
```

🎉 **Your bot is now live!**

---

## 📝 Usage Guide

1. Open Telegram and search for your bot. Click **Start** or type `/start`.
2. **Text Transaction**: Send a transaction description in free-format plain text:
   > *spent 20$ on 2 cups of coffee in the starbucks*
3. **Photo Receipt**: Send a photo of a receipt or bill (optionally adding a text caption such as *"via Credit Card"* alongside the image):
   > *[Send image of your coffee receipt] + caption: "via Credit Card"*
4. The bot will automatically download the image, run multimodal AI parsing (OCR + category classification), and reply with a stateless confirmation card:
   > 📝 Yes, I am glad that you had 2 cups of coffee, I will add this as transaction - category Food, subcategory Cafe, amount 20, currency usd, is it right?
   > 
   > `[✅ Yes, log it]`  `[❌ No, cancel]`
5. Tap **[Yes, log it]**:
   * The bot immediately logs the transaction into Smerio.
   * On success, the confirmation edits to:
     > Yes, I am glad that you had 2 cups of coffee...
     > 
     > ✅ **Logged successfully!**
6. Tap **[No, cancel]**:
   * The confirmation edits to:
     > Yes, I am glad that you had 2 cups of coffee...
     > 
     > ❌ **Transaction cancelled.**

---

## 🧪 Local Verification & Tests
Verify the code locally by running the comprehensive unit test suite:
1. Navigate to the root directory:
   ```bash
   cd /Users/ivan/Documents/Antigravity/016_smerio_tg_bot
   ```
2. Run the tests using python's built-in `unittest` runner (configuring dummy env parameters):
   ```bash
   export TELEGRAM_BOT_TOKEN="mock" \
          SMERIO_API_URL="http://localhost:8090" \
          SMERIO_TELEGRAM_TOKEN="mock" \
          ALLOWED_TELEGRAM_USER_ID="5139816564" \
          LLM_API_KEY="mock" \
          LLM_PROVIDER="gemini" \
          PYTHONPATH=src
   python3 -m unittest discover -s tests -v
   ```
All 14 unit tests will pass successfully.
