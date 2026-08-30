output "state_bucket" {
  value       = google_storage_bucket.terraform_state.name
  description = "Remote Terraform state bucket for foundation/runtime stacks."
}

output "workload_identity_providers" {
  value = {
    for plane, provider in google_iam_workload_identity_pool_provider.github : plane => provider.name
  }
  description = "Workflow-isolated GitHub Workload Identity Providers."
}

output "github_deployer_service_accounts" {
  value = {
    for plane, account in google_service_account.github_deployer : plane => account.email
  }
  description = "Workflow-isolated GitHub deployment identities."
}

output "gitlab_workload_identity_providers" {
  value = {
    for plane, provider in google_iam_workload_identity_pool_provider.gitlab : plane => provider.name
  }
  description = "Protected-project GitLab Workload Identity Providers."
}

output "gitlab_deployer_service_accounts" {
  value = {
    for plane, account in google_service_account.gitlab_deployer : plane => account.email
  }
  description = "Plane-separated GitLab deployment identities."
}
