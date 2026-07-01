import os
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as cloud_logging
from vertexai import agent_engines
from dev_signal_agent.app_utils.env import init_environment

# --- Initialization & Secure Secret Retrieval ---
# We now unpack the SECRETS dictionary returned by our updated env.py
PROJECT_ID, MODEL_LOC, SERVICE_LOC, SECRETS = init_environment()
logger = cloud_logging.Client().logger(__name__)

# Access sensitive credentials from the SECRETS dictionary 
# These keys stay in memory and are NOT injected into os.environ
DEVTO_API_KEY = SECRETS.get("DEVTO_API_KEY")
DK_API_KEY = SECRETS.get("DK_API_KEY")

# Telegram bot needs these in os.environ BEFORE importing bot modules
if SECRETS.get("TELEGRAM_BOT_TOKEN"):
    os.environ["TELEGRAM_BOT_TOKEN"] = SECRETS["TELEGRAM_BOT_TOKEN"]

# Import telegram router AFTER env vars are set
from dev_signal_agent.telegram_bot.routes import router as telegram_router, configure_services

# --- Configuration & Sessions ---
AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Non-sensitive configuration still uses environment variables [cite: 207, 208]
BUCKET = os.environ.get("AI_ASSETS_BUCKET") 
USE_IN_MEMORY = os.environ.get("USE_IN_MEMORY_SESSION", "").lower() in ("true", "1")

# --- MEMORY BANK CONNECTION ---
def _get_memory_bank_uri():
    if USE_IN_MEMORY: return None, None
    # NOTE: Reasoning Engines (Agent Engines) are only available in us-central1
    # Even if the Cloud Run service runs in europe-west1, memory must point to us-central1
    memory_location = os.environ.get("AGENT_ENGINE_LOCATION", "us-central1")
      # Re-init vertexai for the Agent Engine API call (requires us-central1)
    import vertexai as _vtx
    _vtx.init(project=PROJECT_ID, location=memory_location)
    
    name = os.environ.get("AGENT_ENGINE_MEMORY_BANK_NAME", "dev_signal_agent") 
    existing = list(agent_engines.list(filter=f"display_name={name}"))
    ae = existing[0] if existing else agent_engines.create(display_name=name)
    uri = f"agentengine://{ae.resource_name}"
    print(f"DEBUG: Connecting to Memory Bank: {uri} (display_name={name}, location={memory_location})")
    
    # Keep vertexai pointed at us-central1 (Agent Engine location).
    # The Gemini model location is specified per-agent via MODEL_LOC in agent.py,
    # so global vertexai location only matters for Agent Engine (sessions/memory).
    
    return uri, uri

SESSION_URI, MEMORY_URI = _get_memory_bank_uri()

# Sessions and Memory are both persisted via Agent Engine.
# This ensures sessions survive Cloud Run scale-to-zero events.

# --- Initialize FastAPI with ADK ---
app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=f"gs://{BUCKET}" if BUCKET else None,
    allow_origins=["*"],
    session_service_uri=SESSION_URI,
    memory_service_uri=MEMORY_URI,
    otel_to_cloud=True,
)

# --- Telegram Bot Routes ---
# Share Agent Engine URIs so Telegram uses the SAME persistent backend
print(f"DEBUG: Configuring Telegram services with session_uri={SESSION_URI}, memory_uri={MEMORY_URI}")
configure_services(session_uri=SESSION_URI, memory_uri=MEMORY_URI)
app.include_router(telegram_router)

if __name__ == "__main__":
    import uvicorn
    # Standard Cloud Run port is 8080 
    uvicorn.run(app, host="0.0.0.0", port=8080)