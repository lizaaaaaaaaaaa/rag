# terraform/main.tf
# Terraform設定（インフラ自動化）

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
  default     = "rag-cloud-project"
}

variable "region" {
  description = "Google Cloud Region"
  type        = string
  default     = "asia-northeast1"
}

# Secret Manager
resource "google_secret_manager_secret" "line_access_token" {
  secret_id = "LINE_CHANNEL_ACCESS_TOKEN"
  
  replication {
    automatic = true
  }
}

resource "google_secret_manager_secret" "line_channel_secret" {
  secret_id = "LINE_CHANNEL_SECRET"
  
  replication {
    automatic = true
  }
}

# Cloud Run Service
resource "google_cloud_run_service" "rag_api" {
  name     = "rag-api"
  location = var.region

  template {
    spec {
      containers {
        image = "gcr.io/${var.project_id}/rag-api:financial"
        
        ports {
          container_port = 8080
        }
        
        env {
          name  = "LINE_BOT_MODE"
          value = "ultra_fast_financial"
        }
        
        env {
          name  = "ENABLE_FINANCIAL_PLANNING"
          value = "true"
        }
        
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        
        resources {
          limits = {
            memory = "2Gi"
            cpu    = "1"
          }
        }
      }
      
      timeout_seconds = 300
      container_concurrency = 80
    }
    
    metadata {
      annotations = {
        "autoscaling.knative.dev/minScale" = "1"
        "autoscaling.knative.dev/maxScale" = "10"
        "run.googleapis.com/cpu-throttling" = "false"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

# Cloud Run IAM
resource "google_cloud_run_service_iam_binding" "public_access" {
  location = google_cloud_run_service.rag_api.location
  project  = google_cloud_run_service.rag_api.project
  service  = google_cloud_run_service.rag_api.name
  role     = "roles/run.invoker"
  members  = ["allUsers"]
}

# Service Account権限
resource "google_project_iam_binding" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  
  members = [
    "serviceAccount:${google_cloud_run_service.rag_api.template[0].spec[0].service_account_name}",
  ]
}

# 出力
output "service_url" {
  value = google_cloud_run_service.rag_api.status[0].url
}

output "webhook_url" {
  value = "${google_cloud_run_service.rag_api.status[0].url}/line/webhook"
}

output "liff_page_url" {
  value = "${google_cloud_run_service.rag_api.status[0].url}/financial/liff-page"
}