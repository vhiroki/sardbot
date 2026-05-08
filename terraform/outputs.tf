output "bucket_name" {
  value       = google_storage_bucket.state.name
  description = "GCS bucket where sardbot state lives"
}

output "service_account_email" {
  value       = google_service_account.sardbot.email
  description = "Cloud Run Job runtime service account"
}

output "image_repo" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/sardbot/sardbot"
  description = "Artifact Registry repo URL — push images here"
}

output "scheduler_job_name" {
  value       = google_cloud_scheduler_job.sardbot_daily.name
  description = "Cloud Scheduler job that triggers the bot daily"
}

output "manual_run_command" {
  value       = "gcloud run jobs execute ${google_cloud_run_v2_job.sardbot.name} --region=${var.region}"
  description = "Run the job manually for testing"
}

output "webhook_url" {
  value       = google_cloud_run_v2_service.webhook.uri
  description = "Telegram webhook URL — register with setWebhook"
}
