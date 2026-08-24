variable "project_id" {
  type        = string
  description = "Existing Google Cloud project ID. Billing must already be attached."
}

variable "region" {
  type        = string
  description = "Primary Google Cloud region."
  default     = "europe-central2"
}

variable "github_repository" {
  type        = string
  description = "GitHub repository in owner/name form."
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be owner/name."
  }
}

variable "github_repository_id" {
  type        = string
  description = "Immutable numeric GitHub repository ID, represented as a string."
  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be the immutable numeric repository ID."
  }
}

variable "github_owner_id" {
  type        = string
  description = "Immutable numeric GitHub repository owner ID, represented as a string."
  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id must be the immutable numeric owner ID."
  }
}

variable "github_deploy_branch" {
  type        = string
  description = "Only this branch may impersonate the deployment service account."
  default     = "main"
}

variable "state_retention_seconds" {
  type        = number
  description = "Minimum retention for Terraform state object generations."
  default     = 2592000
  validation {
    condition     = var.state_retention_seconds >= 604800
    error_message = "State retention must be at least seven days."
  }
}
