variable "autoscale_handler_unique_identifier" {
  description = "asg_dns_handler"

  type = string
}

variable "vpc_name" {
  description = "The name of the VPC. Typically the DNS zone eg example.com"

  type = string
}

variable "autoscale_route53zone_arn" {
  description = "The ARN of route53 zone associated with autoscaling group"

  type = string
}

variable "hostname_tag_name_private" {
    type = string
    default = "asg:hostname_pattern_private"
}

variable "hostname_tag_name_public" {
    type = string
    default = "asg:hostname_pattern_public"
}

variable "autoscale_dns_timer_minutes" {
  type = number
  default = 15
}