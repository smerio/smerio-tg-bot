output "webhook_url" {
  value       = "${aws_apigatewayv2_stage.default.invoke_url}webhook"
  description = "The HTTP POST Webhook URL to register with @BotFather to link your Telegram bot to AWS"
}

output "lambda_function_name" {
  value       = aws_lambda_function.bot.function_name
  description = "The dynamically created Lambda function name"
}
