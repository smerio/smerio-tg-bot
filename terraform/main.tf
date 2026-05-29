terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  # Prefix to isolate resources in the same AWS account without collision
  resource_prefix = "smerio-bot-${var.bot_id}"
  lambda_src_dir  = "${path.module}/../src"
}

# ---------------------------------------------------------------------------
# Lambda Packaging
# ---------------------------------------------------------------------------

# Zip the local application source code
data "archive_file" "lambda_src" {
  type        = "zip"
  source_dir  = local.lambda_src_dir
  output_path = "${path.module}/.build/lambda_src.zip"
}

# Lambda layer for external dependencies (requests, python-dotenv, anthropic, etc.)
# Before running 'terraform apply', the user runs:
# pip install -r requirements.txt -t layer/python
data "archive_file" "deps_layer" {
  type        = "zip"
  source_dir  = "${path.module}/../layer"
  output_path = "${path.module}/.build/deps_layer.zip"
}

resource "aws_lambda_layer_version" "deps" {
  filename            = data.archive_file.deps_layer.output_path
  layer_name          = "${local.resource_prefix}-deps"
  source_code_hash    = data.archive_file.deps_layer.output_base64sha256
  compatible_runtimes = ["python3.12"]
}

# ---------------------------------------------------------------------------
# IAM Roles & Permissions
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.resource_prefix}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Permission to allow the Lambda to call itself asynchronously (Fast Path webhook)
data "aws_iam_policy_document" "self_invoke" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.resource_prefix}"]
  }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role_policy" "self_invoke" {
  name   = "${local.resource_prefix}-self-invoke"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.self_invoke.json
}

# ---------------------------------------------------------------------------
# Webhook Lambda Function
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "bot" {
  name              = "/aws/lambda/${local.resource_prefix}"
  retention_in_days = 14
}

resource "aws_lambda_function" "bot" {
  function_name    = local.resource_prefix
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 60
  memory_size      = 512
  filename         = data.archive_file.lambda_src.output_path
  source_code_hash = data.archive_file.lambda_src.output_base64sha256
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = {
      BOT_ID                   = var.bot_id
      ALLOWED_TELEGRAM_USER_ID = var.allowed_telegram_user_id
      TELEGRAM_BOT_TOKEN       = var.telegram_bot_token
      SMERIO_API_URL           = var.smerio_api_url
      SMERIO_TELEGRAM_TOKEN    = var.smerio_telegram_token
      LLM_PROVIDER             = var.llm_provider
      LLM_API_KEY              = var.llm_api_key
      LLM_MODEL                = var.llm_model
    }
  }

  depends_on = [aws_cloudwatch_log_group.bot]
}

# ---------------------------------------------------------------------------
# API Gateway HTTP API (Telegram Webhook Endpoint)
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "webhook" {
  name          = "${local.resource_prefix}-apigw"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "webhook" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.bot.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "webhook" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook"
  target    = "integrations/${aws_apigatewayv2_integration.webhook.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.bot.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}
