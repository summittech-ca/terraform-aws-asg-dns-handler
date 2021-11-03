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

# variable "use_public_ip" {
#   description = "Use public IP instead of private"

#   type    = bool
#   default = false
# }

variable "multi_host" {
  description = "Configures the module to to add all hosts in the ASG to a single route. Note that '#instanceid' will be silently ignored in this mode"

  type    = bool
  default = false
}

variable "hostname_tag_name_private" {
    type = string
    default = "asg:hostname_pattern_private"
}

variable "hostname_tag_name_public" {
    type = string
    default = "asg:hostname_pattern_public"
}
