output "autoscale_handling_sns_topic_arn" {
  description = "SNS topic ARN for autoscaling group"
  value       = aws_sns_topic.autoscale_handling.arn
}

output "agent_lifecycle_iam_role_arn" {
  description = "IAM Role ARN for lifecycle_hooks"
  value       = aws_iam_role.lifecycle.arn
}

