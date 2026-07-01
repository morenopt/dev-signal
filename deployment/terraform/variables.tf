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
 description = "A map of secret names and their values (e.g., DEVTO_API_KEY, DK_API_KEY, DAILYDEV_API_TOKEN, TELEGRAM_BOT_TOKEN)"
 type        = map(string)
 default     = {}
}
variable "ai_assets_bucket" {
 description = "The GCS bucket for storing AI assets"
 type        = string
}
variable "owner_email" {
 description = "Email of the sole user allowed to invoke the Cloud Run service"
 type        = string
}
variable "telegram_owner_chat_id" {
 description = "Telegram chat ID of the bot owner (for private bot access)"
 type        = string
 default     = ""
}
