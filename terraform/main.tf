terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# -----------------------------------------------------------------------------
# Required APIs
# -----------------------------------------------------------------------------
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# -----------------------------------------------------------------------------
# Service account that the Cloud Run Job runs as
# -----------------------------------------------------------------------------
resource "google_service_account" "sardbot" {
  account_id   = "sardbot-runner"
  display_name = "Sardbot Cloud Run Job runner"
  depends_on   = [google_project_service.apis]
}

# -----------------------------------------------------------------------------
# Cloud Storage bucket for state + trade logs + price cache
# -----------------------------------------------------------------------------
resource "google_storage_bucket" "state" {
  name                        = "${var.project_id}-sardbot-state"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
  versioning {
    # Versioning protects against accidental state overwrites — cheap insurance
    # for a tiny bucket like this.
    enabled = true
  }
  lifecycle_rule {
    condition { num_newer_versions = 30 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "sardbot_bucket" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.sardbot.email}"
}

# -----------------------------------------------------------------------------
# Artifact Registry for the container image
# -----------------------------------------------------------------------------
resource "google_artifact_registry_repository" "sardbot" {
  location      = var.region
  repository_id = "sardbot"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# -----------------------------------------------------------------------------
# Secrets — Telegram bot token and chat ID
# -----------------------------------------------------------------------------
resource "google_secret_manager_secret" "telegram_token" {
  secret_id = "sardbot-telegram-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "telegram_chat" {
  secret_id = "sardbot-telegram-chat"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "telegram_token_access" {
  secret_id = google_secret_manager_secret.telegram_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sardbot.email}"
}

resource "google_secret_manager_secret_iam_member" "telegram_chat_access" {
  secret_id = google_secret_manager_secret.telegram_chat.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sardbot.email}"
}

# -----------------------------------------------------------------------------
# Cloud Run Job
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_job" "sardbot" {
  name                = "sardbot-paper-trade"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.sardbot.email
      timeout         = "300s"
      max_retries     = 1

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/sardbot/sardbot:${var.image_tag}"

        env {
          name  = "SARDBOT_STORAGE"
          value = "gcs:${google_storage_bucket.state.name}"
        }
        env {
          name = "TELEGRAM_BOT_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.telegram_token.secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "TELEGRAM_CHAT_ID"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.telegram_chat.secret_id
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
    }
  }
  depends_on = [
    google_project_service.apis,
    google_artifact_registry_repository.sardbot,
  ]
}

# -----------------------------------------------------------------------------
# Webhook secret (used to validate Telegram → us POSTs)
# -----------------------------------------------------------------------------
resource "google_secret_manager_secret" "webhook_secret" {
  secret_id = "sardbot-webhook-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "webhook_secret_access" {
  secret_id = google_secret_manager_secret.webhook_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sardbot.email}"
}

# -----------------------------------------------------------------------------
# Cloud Run Service — Telegram webhook listener
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "webhook" {
  name                = "sardbot-webhook"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.sardbot.email
    timeout         = "60s"

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image   = "${var.region}-docker.pkg.dev/${var.project_id}/sardbot/sardbot:${var.image_tag}"
      command = ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "55", "sardbot.paper.webhook:app"]

      ports {
        container_port = 8080
      }

      env {
        name  = "SARDBOT_STORAGE"
        value = "gcs:${google_storage_bucket.state.name}"
      }
      env {
        name = "TELEGRAM_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.telegram_token.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "TELEGRAM_CHAT_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.telegram_chat.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "WEBHOOK_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.webhook_secret.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }
  depends_on = [
    google_project_service.apis,
    google_artifact_registry_repository.sardbot,
    google_secret_manager_secret_iam_member.webhook_secret_access,
  ]
}

# Allow public unauthenticated access — Telegram is the caller and can't
# authenticate with GCP IAM. Security comes from WEBHOOK_SECRET + chat_id check.
resource "google_cloud_run_v2_service_iam_member" "webhook_public" {
  project  = google_cloud_run_v2_service.webhook.project
  location = google_cloud_run_v2_service.webhook.location
  name     = google_cloud_run_v2_service.webhook.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# -----------------------------------------------------------------------------
# CI/CD — Workload Identity Federation for GitHub Actions
# -----------------------------------------------------------------------------
# Lets GitHub Actions assume a GCP service account WITHOUT a JSON key. The
# auth flow uses GitHub's OIDC token. We bind the workflow to a specific
# repository via attribute_condition so other repos can't impersonate.

resource "google_iam_workload_identity_pool" "github" {
  count                     = var.github_repo == "" ? 0 : 1
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions Pool"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count                              = var.github_repo == "" ? 0 : 1
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub Actions Provider"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "assertion.repository == '${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "ci_deployer" {
  count        = var.github_repo == "" ? 0 : 1
  account_id   = "sardbot-ci-deployer"
  display_name = "Sardbot CI deployer (GitHub Actions)"
  depends_on   = [google_project_service.apis]
}

# Bind the GitHub repo to the CI service account via WIF.
resource "google_service_account_iam_member" "github_wif_binding" {
  count              = var.github_repo == "" ? 0 : 1
  service_account_id = google_service_account.ci_deployer[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repo}"
}

# Permissions for CI: push images, update Cloud Run resources.
resource "google_project_iam_member" "ci_artifact_writer" {
  count   = var.github_repo == "" ? 0 : 1
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.ci_deployer[0].email}"
}

resource "google_project_iam_member" "ci_run_admin" {
  count   = var.github_repo == "" ? 0 : 1
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.ci_deployer[0].email}"
}

# Cloud Run resources run as `sardbot-runner` SA. Updating them requires
# `serviceAccountUser` on that runner SA — scoped narrowly, not project-wide.
resource "google_service_account_iam_member" "ci_act_as_runner" {
  count              = var.github_repo == "" ? 0 : 1
  service_account_id = google_service_account.sardbot.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.ci_deployer[0].email}"
}

# -----------------------------------------------------------------------------
# Cloud Scheduler — daily trigger at 00:05 UTC (after BTC daily candle closes)
# -----------------------------------------------------------------------------
resource "google_service_account" "scheduler" {
  account_id   = "sardbot-scheduler"
  display_name = "Sardbot Cloud Scheduler invoker"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "scheduler_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "sardbot_daily" {
  name        = "sardbot-paper-trade-daily"
  description = "Trigger sardbot paper-trade after daily BTC candle closes"
  schedule    = "5 0 * * *"
  time_zone   = "Etc/UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.sardbot.name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }
  depends_on = [google_project_service.apis]
}
