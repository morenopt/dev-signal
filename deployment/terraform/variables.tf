variable "project_id" {
 description = "The Google Cloud Project ID"
 type        = string
}
variable "region" {
 description = "The Google Cloud region to deploy to"
 type        = string
 default     = "europe-west1"
}
variable "service_name" {
 description = "The name of the Cloud Run service"
 type        = string
 default     = "dev-signal"
}
variable "secrets" {
 description = "A map of secret names and their values (e.g., DEVTO_API_KEY, DK_API_KEY)"
 type        = map(string)
 default     = {}
}
variable "ai_assets_bucket" {
 description = "The GCS bucket for storing AI assets"
 type        = string
}
