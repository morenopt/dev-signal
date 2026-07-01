
# 1. Enable Required Google Cloud APIs
resource "google_project_service" "services" {
  project = var.project_id
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
    "logging.googleapis.com"
  ])
  service            = each.key
  disable_on_destroy = false
}

# 2. Artifact Registry for Container Images
resource "google_artifact_registry_repository" "repo" {
  project       = var.project_id
  location      = var.region
  repository_id = "dev-signal"
  description   = "Docker repository for Dev Signal Agent"
  format        = "DOCKER"
  depends_on    = [google_project_service.services]
}

# 3. Dedicated Service Account for Least Privilege
resource "google_service_account" "agent_sa" {
  project      = var.project_id
  account_id   = "${var.service_name}-sa"
  display_name = "Dev Signal Agent Service Account"
}

# 4. IAM Permissions for Vertex AI, Logging, and Storage
resource "google_project_iam_member" "vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.agent_sa.email}"
}

resource "google_project_iam_member" "log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.agent_sa.email}"
}

resource "google_project_iam_member" "storage_user" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.agent_sa.email}"
}

# 5. Secret Manager Configuration
resource "google_secret_manager_secret" "agent_secrets" {
  project   = var.project_id
  for_each  = toset(keys(var.secrets))
  secret_id = each.key
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_version" "agent_secrets_version" {
  for_each    = toset(keys(var.secrets))
  secret      = google_secret_manager_secret.agent_secrets[each.key].id
  secret_data = var.secrets[each.key]
}

# IMPORTANT: Grants the SA permission to CALL the Secret Manager API
resource "google_secret_manager_secret_iam_member" "secret_accessor" {
  project   = var.project_id
  for_each  = toset(keys(var.secrets))
  secret_id = google_secret_manager_secret.agent_secrets[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent_sa.email}"
}

# 6. Cloud Run Service Deployment
resource "google_cloud_run_v2_service" "default" {
  project  = var.project_id
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.agent_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 20
    }

    containers {
      image = "europe-west1-docker.pkg.dev/optimum-web-487816-v4/dev-signal/dev-signal:latest"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "True"
      }
      env {
        name  = "AI_ASSETS_BUCKET"
        value = var.ai_assets_bucket
      }
      env {
        name  = "GOOGLE_CLOUD_REGION"
        value = var.region
      }
      env {
        name  = "AGENT_ENGINE_LOCATION"
                value = "europe-west1"
      }
      env {
        name  = "TELEGRAM_OWNER_CHAT_ID"
        value = var.telegram_owner_chat_id
      }      # Secret environment variables — injected from Secret Manager
      env {
        name  = "DEPLOY_TIMESTAMP"
        value = "managed-by-terraform"
      }
      env {
        name = "DEVTO_API_KEY"
        value_source {
          secret_key_ref {
            secret  = "DEVTO_API_KEY"
            version = "latest"
          }
        }
      }
      env {
        name = "DK_API_KEY"
        value_source {
          secret_key_ref {
            secret  = "DK_API_KEY"
            version = "latest"
          }
        }
      }
      env {
        name = "DAILYDEV_API_TOKEN"
        value_source {
          secret_key_ref {
            secret  = "DAILYDEV_API_TOKEN"
            version = "latest"
          }
        }
      }
      env {
        name = "TELEGRAM_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = "TELEGRAM_BOT_TOKEN"
            version = "latest"
          }
        }
      }

      resources {
        limits = {          cpu    = "1"
          memory = "1Gi"
        }
        startup_cpu_boost = true
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [google_project_service.services]
}

# 7. IAM: Private access — only the owner can invoke the service
resource "google_cloud_run_v2_service_iam_member" "owner_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.default.name
  role     = "roles/run.invoker"
  member   = "user:${var.owner_email}"
}

# 8. Cloud Scheduler: Daily trend alert (triggers Telegram bot)
resource "google_cloud_scheduler_job" "daily_trends" {
  project     = var.project_id
  region      = var.region
  name        = "${var.service_name}-daily-trends"
  description = "Triggers daily trend scan every morning at 8:00 CET"
  schedule    = "0 8 * * *"
  time_zone   = "Europe/Lisbon"
  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.default.uri}/telegram/cron/trends"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{\"topic\": \"gcp\"}")

    oidc_token {
      service_account_email = google_service_account.agent_sa.email
      audience              = google_cloud_run_v2_service.default.uri
    }
  }

  # No retries — the endpoint is idempotent but we avoid duplicate messages.
  # If it fails, we'll see it in Cloud Logging and can trigger manually.
  retry_config {
    retry_count = 0
  }

  depends_on = [google_project_service.services]
}

# Grant Cloud Scheduler SA permission to invoke Cloud Run
resource "google_cloud_run_v2_service_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.default.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.agent_sa.email}"
}
