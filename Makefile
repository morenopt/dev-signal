PROJECT_ID ?= $(shell gcloud config get-value project)
REGION ?= europe-west1
IMAGE_REPO ?= dev-signal
IMAGE := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(IMAGE_REPO)/dev-signal:latest

# Build and deploy to Cloud Run
docker-deploy:
	@echo "🚀 Building and deploying to $(PROJECT_ID) via Cloud Build..."
	gcloud builds submit --tag $(IMAGE) --region $(REGION)
	gcloud run deploy dev-signal \
		--image $(IMAGE) \
		--region $(REGION) \
		--platform managed
