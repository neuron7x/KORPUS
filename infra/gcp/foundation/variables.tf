variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-central2"
}

variable "name_prefix" {
  type    = string
  default = "korpus-prod"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name_prefix))
    error_message = "name_prefix must be a lowercase resource-name prefix."
  }
}


variable "runtime_subnet_cidr" {
  type        = string
  description = "Dedicated RFC1918 subnet used by Direct VPC egress from Cloud Run workloads."
  default     = "10.42.0.0/24"
  validation {
    condition = (
      can(cidrhost(var.runtime_subnet_cidr, 0))
      && tonumber(split("/", var.runtime_subnet_cidr)[1]) <= 26
    )
    error_message = "runtime_subnet_cidr must be a valid IPv4 CIDR with /26 or more address space."
  }
}

variable "private_service_range_prefix_length" {
  type        = number
  description = "Google-managed Private Services Access allocation prefix for managed services such as Cloud SQL."
  default     = 16
  validation {
    condition     = var.private_service_range_prefix_length >= 16 && var.private_service_range_prefix_length <= 24
    error_message = "private_service_range_prefix_length must be between /16 and /24."
  }
}

variable "database_tier" {
  type        = string
  description = "Cloud SQL machine tier. Keep explicit so capacity changes are reviewed."
  default     = "db-custom-2-7680"
}

variable "database_disk_size_gb" {
  type    = number
  default = 50
  validation {
    condition     = var.database_disk_size_gb >= 20
    error_message = "Production database disk must be at least 20 GiB."
  }
}

variable "database_disk_autoresize_limit_gb" {
  type        = number
  description = "Explicit finite Cloud SQL storage auto-growth ceiling in GiB. No default: production owner must choose it deliberately."
  validation {
    condition     = var.database_disk_autoresize_limit_gb >= var.database_disk_size_gb
    error_message = "database_disk_autoresize_limit_gb must be finite and >= database_disk_size_gb."
  }
}

variable "object_retention_seconds" {
  type    = number
  default = 2592000
}

variable "audit_retention_seconds" {
  type    = number
  default = 31536000
}

variable "governance_retention_seconds" {
  type    = number
  default = 31536000
}

variable "lock_retention_policies" {
  type        = bool
  description = "Irreversible Bucket Lock. Enable only after the production retention policy is formally approved."
  default     = false
}

variable "github_runtime_deployer_service_account" {
  type        = string
  description = "GitHub WIF deployer service-account email; actAs is granted only on KORPUS runtime identities."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\\.iam\\.gserviceaccount\\.com$", var.github_runtime_deployer_service_account))
    error_message = "github_runtime_deployer_service_account must be a Google service-account email."
  }
}

variable "github_drill_deployer_service_account" {
  type        = string
  description = "GitHub WIF DR-drill service-account email; receives only Cloud SQL drill control-plane access."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\\.iam\\.gserviceaccount\\.com$", var.github_drill_deployer_service_account))
    error_message = "github_drill_deployer_service_account must be a Google service-account email."
  }
}
