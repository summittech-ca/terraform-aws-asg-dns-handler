locals {
  lambda_pkg = data.archive_file.multihost
}

resource "aws_sns_topic" "autoscale_handling" {
  name = format("%s", var.autoscale_handler_unique_identifier)
}

# This is to optionally manage the CloudWatch Log Group for the Lambda Function.
# If skipping this resource configuration, also add "logs:CreateLogGroup" to the IAM policy below.
resource "aws_cloudwatch_log_group" "example" {
  name              = format("/aws/lambda/%s", var.autoscale_handler_unique_identifier)
  retention_in_days = 14
}

resource "aws_lambda_function" "autoscale_handling" {
  depends_on = [aws_sns_topic.autoscale_handling]

  filename         = local.lambda_pkg.output_path
  function_name    = format("%s", var.autoscale_handler_unique_identifier)
  role             = aws_iam_role.autoscale_handling.arn
  handler          = "autoscale.lambda_handler"
  runtime          = "python3.8"
  source_code_hash = filebase64sha256(local.lambda_pkg.output_path)
  description      = "Handles DNS for autoscaling groups by receiving autoscaling notifications and setting/deleting records from route53"
  environment {
    variables = {
      # "use_public_ip" = var.use_public_ip
      "hostname_tag_name_private" = var.hostname_tag_name_private
      "hostname_tag_name_public" = var.hostname_tag_name_public
      # "hostname_tag_name" = var.hostname_tag_name
    }
  }
}

resource "aws_lambda_permission" "autoscale_handling" {
  depends_on = [aws_lambda_function.autoscale_handling]

  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.autoscale_handling.arn
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.autoscale_handling.arn
}

resource "aws_sns_topic_subscription" "autoscale_handling" {
  depends_on = [aws_lambda_permission.autoscale_handling]

  topic_arn = aws_sns_topic.autoscale_handling.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.autoscale_handling.arn
}

data "archive_file" "multihost" {
  type        = "zip"
  source_file = format("%s/lambda/multihost/autoscale.py", path.module)
  output_path = format("%s/lambda/dist/multihost.zip", path.module)
}

resource "aws_iam_role_policy" "autoscale_handling" {
  name = format("%s", var.autoscale_handler_unique_identifier)
  role = aws_iam_role.autoscale_handling.name

  policy = data.aws_iam_policy_document.autoscale_handling_document.json
}

resource "aws_iam_role" "autoscale_handling" {
  name               = format("%s", var.autoscale_handler_unique_identifier)
  assume_role_policy = data.aws_iam_policy_document.assume_lambda_role_policy_document.json
}

resource "aws_iam_role" "lifecycle" {
  name               = format("%s-lifecycle", var.autoscale_handler_unique_identifier)
  assume_role_policy = data.aws_iam_policy_document.lifecycle_role.json
}

data "aws_iam_policy_document" "assume_lambda_role_policy_document" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "lifecycle_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["autoscaling.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "lifecycle_policy" {
  name   = format("%s-lifecycle", var.autoscale_handler_unique_identifier)
  role   = aws_iam_role.lifecycle.id
  policy = data.aws_iam_policy_document.lifecycle_policy.json
}

data "aws_iam_policy_document" "lifecycle_policy" {
  statement {
    effect    = "Allow"
    actions   = ["sns:Publish", "autoscaling:CompleteLifecycleAction"]
    resources = [aws_sns_topic.autoscale_handling.arn]
  }
}

data "aws_iam_policy_document" "autoscale_handling_document" {
  statement {
    actions = [
      # "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:*:*:*"
    ]
  }
  statement {
    actions = [
      "autoscaling:DescribeTags",
      "autoscaling:DescribeAutoScalingGroups",
      "autoscaling:CompleteLifecycleAction",
      "ec2:DescribeInstances",
      "route53:GetHostedZone",
      "ec2:CreateTags"
    ]
    resources = [
      "*"
    ]
  }
  statement {
    actions = [
      "route53:ChangeResourceRecordSets",
      "route53:ListResourceRecordSets"
    ]
    resources = [
      format("arn:aws:route53:::hostedzone/%s", var.autoscale_route53zone_arn)
    ]
  }
}

resource "aws_iam_role_policy" "update_dns_policy" {
  role = aws_iam_role.autoscale_handling.name

	# Terraform's "jsonencode" function converts a
	# Terraform expression result to valid JSON syntax.
	policy = jsonencode({
		Version = "2012-10-17"
		Statement = [
			{
				Action = [
					"route53:*",
				]
				Effect   = "Allow"
				Resource = "${var.autoscale_route53zone_arn}"
			},
		]
	})
}
