provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "bootstrap" {
  for_each = toset([
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
    "storage.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "terraform_state" {
  name                        = "${var.project_id}-korpus-tfstate"
  project                     = var.project_id
  location                    = "EU"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = var.state_retention_seconds
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.bootstrap]
}

locals {
  deployment_planes = {
    foundation = {
      account_id    = "korpus-github-foundation"
      display_name  = "KORPUS GitHub foundation identity"
      pool_id       = "korpus-github-foundation"
      workflow_path = ".github/workflows/gcp-foundation.yml"
    }
    runtime = {
      account_id    = "korpus-github-runtime"
      display_name  = "KORPUS GitHub runtime identity"
      pool_id       = "korpus-github-runtime"
      workflow_path = ".github/workflows/gcp-production.yml"
    }
    drill = {
      account_id    = "korpus-github-drill"
      display_name  = "KORPUS GitHub DR drill identity"
      pool_id       = "korpus-github-drill"
      workflow_path = ".github/workflows/gcp-drill.yml"
    }
  }

  # Foundation is the only CI identity allowed to mutate IAM, service APIs,
  # Cloud SQL control-plane, secret containers/versions, or durable storage policy.
  foundation_project_roles = toset([
    "roles/artifactregistry.admin",
    "roles/cloudsql.admin",
    "roles/compute.securityAdmin",
    "roles/iam.roleAdmin",
    "roles/iam.serviceAccountAdmin",
    "roles/resourcemanager.projectIamAdmin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.admin",
  ])
}

resource "google_service_account" "github_deployer" {
  for_each = local.deployment_planes

  project      = var.project_id
  account_id   = each.value.account_id
  display_name = each.value.display_name
}

resource "google_iam_workload_identity_pool" "github" {
  for_each = local.deployment_planes

  project                   = var.project_id
  workload_identity_pool_id = each.value.pool_id
  display_name              = "KORPUS ${each.key} GitHub Actions"
  description               = "Keyless ${each.key} plane for the canonical KORPUS repository."
}

resource "google_iam_workload_identity_pool_provider" "github" {
  for_each = local.deployment_planes

  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[each.key].workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub Actions ${each.key}"

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
    "attribute.ref_type"            = "assertion.ref_type"
    "attribute.workflow_ref"        = "assertion.workflow_ref"
  }

  # GitHub is a shared OIDC issuer. Admission therefore binds mutable name +
  # immutable repository/owner IDs + exact protected ref + exact workflow file.
  attribute_condition = join(" && ", [
    "assertion.repository == '${var.github_repository}'",
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.repository_owner_id == '${var.github_owner_id}'",
    "assertion.ref_type == 'branch'",
    "assertion.ref == 'refs/heads/${var.github_deploy_branch}'",
    "assertion.workflow_ref == '${var.github_repository}/${each.value.workflow_path}@refs/heads/${var.github_deploy_branch}'",
  ])

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_wif" {
  for_each = local.deployment_planes

  service_account_id = google_service_account.github_deployer[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[each.key].name}/attribute.repository_id/${var.github_repository_id}"
}

# GitLab is a separate trust plane. It receives distinct service accounts and
# pools so revoking GitHub cannot affect GitLab (and vice versa), and so audit
# logs identify the delivery system that performed each mutation.
resource "google_service_account" "gitlab_deployer" {
  for_each = local.deployment_planes

  project      = var.project_id
  account_id   = replace(each.value.account_id, "github", "gitlab")
  display_name = replace(each.value.display_name, "GitHub", "GitLab")
}

resource "google_iam_workload_identity_pool" "gitlab" {
  for_each = local.deployment_planes

  project                   = var.project_id
  workload_identity_pool_id = replace(each.value.pool_id, "github", "gitlab")
  display_name              = "KORPUS ${each.key} GitLab CI"
  description               = "Keyless ${each.key} plane for the canonical GitLab KORPUS project."
}

resource "google_iam_workload_identity_pool_provider" "gitlab" {
  for_each = local.deployment_planes

  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.gitlab[each.key].workload_identity_pool_id
  workload_identity_pool_provider_id = "gitlab"
  display_name                       = "GitLab CI ${each.key}"

  attribute_mapping = {
    "google.subject"                  = "assertion.sub"
    "attribute.project_id"            = "assertion.project_id"
    "attribute.namespace_id"          = "assertion.namespace_id"
    "attribute.ref"                   = "assertion.ref"
    "attribute.ref_type"              = "assertion.ref_type"
    "attribute.ref_protected"         = "assertion.ref_protected"
    "attribute.environment"           = "assertion.environment"
    "attribute.environment_protected" = "assertion.environment_protected"
    "attribute.deployment_tier"       = "assertion.deployment_tier"
  }

  # GitLab.com is a shared issuer. Admission is conjunctive: immutable project
  # and namespace IDs, exact protected branch, and protected production
  # environment/tier must all be present in the same job token.
  attribute_condition = join(" && ", [
    "assertion.project_id == '${var.gitlab_project_id}'",
    "assertion.namespace_id == '${var.gitlab_namespace_id}'",
    "assertion.ref_type == 'branch'",
    "assertion.ref == '${var.gitlab_deploy_branch}'",
    "assertion.ref_protected == 'true'",
    "assertion.environment == 'production'",
    "assertion.environment_protected == 'true'",
    "assertion.deployment_tier == 'production'",
  ])

  oidc {
    issuer_uri = "https://gitlab.com"
  }
}

resource "google_service_account_iam_member" "gitlab_wif" {
  for_each = local.deployment_planes

  service_account_id = google_service_account.gitlab_deployer[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.gitlab[each.key].name}/attribute.project_id/${var.gitlab_project_id}"
}

resource "google_project_iam_member" "foundation_deployer" {
  for_each = local.foundation_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.github_deployer["foundation"].email}"
}

# Runtime Terraform needs only object-level access to its remote state. It does
# not receive project-wide Storage Admin from bootstrap.
resource "google_storage_bucket_iam_member" "runtime_state" {
  bucket = google_storage_bucket.terraform_state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.github_deployer["runtime"].email}"
}

resource "google_storage_bucket_iam_member" "gitlab_runtime_state" {
  bucket = google_storage_bucket.terraform_state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.gitlab_deployer["runtime"].email}"
}

resource "google_project_iam_member" "gitlab_foundation_deployer" {
  for_each = local.foundation_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.gitlab_deployer["foundation"].email}"
}
