# Pattern: Multi-State Side-by-Side Terraform Deployments

This document details the engineering pattern to run multiple side-by-side instances of the same serverless codebase (e.g. separate Telegram Bots for different users) in a single AWS account, ensuring zero collision and absolute environment isolation.

---

## 🛑 The Challenge: Resource Overwrite
When deploying the same Terraform codebase for a second user (e.g. setting up a spouse's bot), modifying a single global variable file (like `terraform.tfvars`) and running `terraform apply` causes Terraform to treat the changes as an **in-place update** or **replacement** of the existing resources tracked in `terraform.tfstate`. 

This leads to the first environment being destroyed or mutated into the second environment.

---

## 💡 The Solution: Isolated State & Config Files
To deploy multiple instances completely independently and in parallel, we isolate two key layers:
1. **The State Layer (`*.tfstate`)**: Dictates what physical AWS resources this configuration manages.
2. **The Config Layer (`*.tfvars`)**: Holds parameters (tokens, keys, user IDs, bot prefixes) for this specific environment.

By feeding unique state and variable files to the CLI, we can manage $N$ isolated instances side-by-side under the same Git tree and AWS account.

### Architectural Separation

```
[Local Workspace Root]
  ├── src/                <-- Shared lambda code
  ├── terraform/
       ├── main.tf        <-- Parameterized HCL resource blocks
       ├── ivan.tfvars    <-- Ivan's custom settings (bot_id = "smerio_ivan_bot")
       ├── ivan.tfstate   <-- Ivan's active AWS resources mapping
       ├── olga.tfvars    <-- Olga's custom settings (bot_id = "smerio_olga_bot")
       └── olga.tfstate   <-- Olga's active AWS resources mapping
```

---

## 🛠️ Implementation Details

### 1. Parameterizing Names in `main.tf`
To prevent resource naming conflicts inside AWS, all resource blocks must be prefixed dynamically using a customizable variable (like `bot_id`).

```hcl
# variables.tf
variable "bot_id" {
  type        = string
  description = "A unique identifier prefix for this bot instance"
}

# main.tf
locals {
  resource_prefix = "smerio-bot-${var.bot_id}"
}

resource "aws_lambda_function" "bot" {
  function_name = local.resource_prefix
  # ...
}
```

### 2. Isolated Deployment Commands
Instead of running a generic `terraform apply`, specify the custom state file and variable inputs via CLI flags:

```bash
# Instance 1: Ivan
terraform apply -state=ivan.tfstate -var-file=ivan.tfvars -auto-approve

# Instance 2: Olga
terraform apply -state=olga.tfstate -var-file=olga.tfvars -auto-approve
```

---

## ⚡ Key Benefits
* **Absolute Resource Separation**: Each bot gets its own API Gateway, Lambda function, IAM role, and CloudWatch log group.
* **Independent Lifecycles**: You can modify, upgrade, or destroy Ivan's bot without causing any downtime or state change to Olga's bot.
* **Safe Local Testing**: Allows deploying temporary "sandbox" configurations to AWS for testing without impacting production state.
