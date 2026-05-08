variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region. us-central1 is in the always-free tier; southamerica-east1 has lower latency from Brazil."
  type        = string
  default     = "us-central1"
}

variable "image_tag" {
  description = "Container image tag to deploy"
  type        = string
  default     = "latest"
}
