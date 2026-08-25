variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-central2"
}

variable "state_bucket" {
  type        = string
  description = "Bootstrap-created GCS Terraform state bucket."
}

variable "foundation_state_prefix" {
  type    = string
  default = "korpus/foundation"
}

variable "domain" {
  type        = string
  description = "Canonical production hostname, without scheme."
  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", var.domain))
    error_message = "domain must be a canonical lowercase DNS hostname."
  }
}

variable "api_image" {
  type        = string
  description = "Immutable API image reference. Tags are forbidden."
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.api_image))
    error_message = "api_image must be digest pinned with @sha256:<64 hex>."
  }
}

variable "web_image" {
  type        = string
  description = "Immutable web image reference. Tags are forbidden."
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.web_image))
    error_message = "web_image must be digest pinned with @sha256:<64 hex>."
  }
}

variable "clamav_image" {
  type        = string
  description = "Immutable ClamAV sidecar image reference."
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.clamav_image))
    error_message = "clamav_image must be digest pinned with @sha256:<64 hex>."
  }
}

variable "oidc_issuer" {
  type = string
  validation {
    condition     = can(regex("^https://", var.oidc_issuer))
    error_message = "OIDC issuer must use HTTPS."
  }
}

variable "oidc_jwks_url" {
  type = string
  validation {
    condition     = can(regex("^https://", var.oidc_jwks_url))
    error_message = "OIDC JWKS URL must use HTTPS."
  }
}

variable "oidc_authorization_endpoint" {
  type = string
  validation {
    condition     = can(regex("^https://", var.oidc_authorization_endpoint))
    error_message = "OIDC authorization endpoint must use HTTPS."
  }
}

variable "oidc_token_endpoint" {
  type = string
  validation {
    condition     = can(regex("^https://", var.oidc_token_endpoint))
    error_message = "OIDC token endpoint must use HTTPS."
  }
}

variable "oidc_end_session_endpoint" {
  type    = string
  default = ""
  validation {
    condition     = var.oidc_end_session_endpoint == "" || can(regex("^https://", var.oidc_end_session_endpoint))
    error_message = "OIDC end-session endpoint must be empty or HTTPS."
  }
}

variable "oidc_client_id" {
  type      = string
  sensitive = false
  validation {
    condition     = length(trimspace(var.oidc_client_id)) >= 3
    error_message = "oidc_client_id is required."
  }
}

variable "oidc_audience" {
  type        = string
  description = "Expected access-token audience."
  validation {
    condition     = length(trimspace(var.oidc_audience)) >= 3
    error_message = "oidc_audience is required."
  }
}

variable "governance_release_id" {
  type        = string
  description = "SHA-256 identifier of the immutable governance bundle prefix."
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.governance_release_id))
    error_message = "governance_release_id must be a SHA-256 hex digest."
  }
}

variable "entitlement_profile_sha256" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.entitlement_profile_sha256))
    error_message = "entitlement profile digest must be SHA-256 hex."
  }
}

variable "source_trust_profile_sha256" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.source_trust_profile_sha256))
    error_message = "source trust profile digest must be SHA-256 hex."
  }
}

variable "reviewer_registry_sha256" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.reviewer_registry_sha256))
    error_message = "reviewer registry digest must be SHA-256 hex."
  }
}

variable "corpus_governance_profile_sha256" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.corpus_governance_profile_sha256))
    error_message = "corpus governance profile digest must be SHA-256 hex."
  }
}

variable "calibration_profile_sha256" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.calibration_profile_sha256))
    error_message = "calibration profile digest must be SHA-256 hex."
  }
}


variable "api_stable_traffic" {
  type        = map(number)
  description = "Revision-exact API traffic snapshot captured immediately before deployment. Empty only for first deployment."
  default     = {}
  validation {
    condition = (
      length(var.api_stable_traffic) == 0
      || (sum(values(var.api_stable_traffic)) == 100
          && alltrue([for revision, percent in var.api_stable_traffic : can(regex("^[a-z][a-z0-9-]{0,62}$", revision)) && percent > 0 && percent <= 100 && floor(percent) == percent]))
    )
    error_message = "api_stable_traffic must be empty for first deploy or an immutable revision map summing exactly to 100."
  }
}

variable "web_stable_traffic" {
  type        = map(number)
  description = "Revision-exact web traffic snapshot captured immediately before deployment. Empty only for first deployment."
  default     = {}
  validation {
    condition = (
      length(var.web_stable_traffic) == 0
      || (sum(values(var.web_stable_traffic)) == 100
          && alltrue([for revision, percent in var.web_stable_traffic : can(regex("^[a-z][a-z0-9-]{0,62}$", revision)) && percent > 0 && percent <= 100 && floor(percent) == percent]))
    )
    error_message = "web_stable_traffic must be empty for first deploy or an immutable revision map summing exactly to 100."
  }
}

variable "api_min_instances" {
  type    = number
  default = 1
  validation {
    condition     = var.api_min_instances >= 1
    error_message = "production API must keep at least one warm instance."
  }
}

variable "api_max_instances" {
  type    = number
  default = 20
  validation {
    condition     = var.api_max_instances >= var.api_min_instances && var.api_max_instances <= 100
    error_message = "api_max_instances must be >= min and <= 100."
  }
}

variable "web_min_instances" {
  type    = number
  default = 1
  validation {
    condition     = var.web_min_instances >= 1
    error_message = "production web must keep at least one warm instance."
  }
}

variable "web_max_instances" {
  type    = number
  default = 20
  validation {
    condition     = var.web_max_instances >= var.web_min_instances && var.web_max_instances <= 100
    error_message = "web_max_instances must be >= min and <= 100."
  }
}

variable "worker_instances" {
  type    = number
  default = 1
  validation {
    condition     = var.worker_instances >= 1 && var.worker_instances <= 20
    error_message = "worker_instances must be within [1,20]."
  }
}

variable "embedding_backfill_enabled" {
  type = bool
  default = false
  description = "Provision the bounded singleton semantic reconciliation job; execution remains explicit."
}

variable "embedding_endpoint" {
  type = string
  default = ""
  validation {
    condition = !var.embedding_backfill_enabled || can(regex("^https://", var.embedding_endpoint))
    error_message = "embedding_endpoint must use HTTPS when backfill is enabled."
  }
}

variable "embedding_model_id" {
  type = string
  default = ""
  validation {
    condition = !var.embedding_backfill_enabled || can(regex("^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$", var.embedding_model_id))
    error_message = "embedding_model_id must be a bounded canonical identifier when enabled."
  }
}

variable "embedding_dimensions" {
  type = number
  default = 768
  validation {
    condition = floor(var.embedding_dimensions) == var.embedding_dimensions && var.embedding_dimensions >= 8 && var.embedding_dimensions <= 4000
    error_message = "embedding_dimensions must be an integer within [8,4000]."
  }
}

variable "embedding_token_secret_id" {
  type = string
  default = ""
  description = "Secret Manager secret ID containing the embedding token, never its value."
  validation {
    condition = !var.embedding_backfill_enabled || can(regex("^[A-Za-z][A-Za-z0-9_-]{0,254}$", var.embedding_token_secret_id))
    error_message = "embedding_token_secret_id must name a Secret Manager secret when enabled."
  }
}

variable "embedding_backfill_batch_size" {
  type = number
  default = 32
  validation {
    condition = floor(var.embedding_backfill_batch_size) == var.embedding_backfill_batch_size && var.embedding_backfill_batch_size >= 1 && var.embedding_backfill_batch_size <= 64
    error_message = "embedding_backfill_batch_size must be an integer within [1,64]."
  }
}

variable "embedding_backfill_max_batches" {
  type = number
  default = 100
  validation {
    condition = floor(var.embedding_backfill_max_batches) == var.embedding_backfill_max_batches && var.embedding_backfill_max_batches >= 1 && var.embedding_backfill_max_batches <= 10000
    error_message = "embedding_backfill_max_batches must be an integer within [1,10000]."
  }
}

variable "notification_channel_ids" {
  type        = list(string)
  description = "Existing Cloud Monitoring notification-channel resource names. Production requires at least one real delivery channel."
  validation {
    condition     = length(var.notification_channel_ids) >= 1 && alltrue([for id in var.notification_channel_ids : can(regex("^projects/[^/]+/notificationChannels/[0-9]+$", id))])
    error_message = "notification_channel_ids must contain at least one full Cloud Monitoring notification channel resource name."
  }
}

variable "otlp_endpoint" {
  type    = string
  default = ""
  validation {
    condition     = var.otlp_endpoint == "" || can(regex("^https://", var.otlp_endpoint))
    error_message = "OTLP endpoint must be empty or HTTPS."
  }
}

variable "availability_slo_goal" {
  type        = number
  default     = 0.995
  description = "Initial production edge availability SLO [EXTRAPOLATED_POLICY]. This is an operator objective, not measured availability."
  validation {
    condition     = var.availability_slo_goal >= 0.99 && var.availability_slo_goal <= 0.999
    error_message = "availability_slo_goal must be within [0.99,0.999]."
  }
}

variable "availability_slo_rolling_days" {
  type        = number
  default     = 30
  description = "Rolling SLO compliance period in days; Cloud Monitoring supports 1..30."
  validation {
    condition     = var.availability_slo_rolling_days >= 1 && var.availability_slo_rolling_days <= 30 && floor(var.availability_slo_rolling_days) == var.availability_slo_rolling_days
    error_message = "availability_slo_rolling_days must be an integer within [1,30]."
  }
}
