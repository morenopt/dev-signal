# Dev Signal — AI-Powered Blog Creation Pipeline

An intelligent multi-agent system that discovers tech trends, drafts blog posts, publishes to Dev.to, and generates promotion content — all orchestrated via Telegram and a web UI.

## 🚀 What It Does

Dev Signal automates the full content creation pipeline:

1. **Discovery** — Scans 400+ tech sources via daily.dev (HN, Dev.to, Medium, Reddit, InfoQ, GitHub…) for trending topics
2. **Research** — Synthesizes official GCP documentation with community insights
3. **Creation** — Drafts professional blog posts with AI-generated images
4. **Publishing** — Publishes directly to Dev.to (as draft or live)
5. **Promotion** — Generates channel-specific drafts for LinkedIn, Hacker News, and daily.dev
6. **Alerts** — Daily trend alerts via Telegram + on-demand interaction

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Cloud Run (europe-west1)                   │
├─────────────────────────────────────────────────────────────┤
│  FastAPI App                                                 │
│  ├── ADK Web UI (/dev-ui)                                    │
│  └── Telegram Bot (/telegram/webhook, /telegram/cron/trends) │
├─────────────────────────────────────────────────────────────┤
│  ADK Runner + Agent Engine (europe-west1)                    │
│  ├── VertexAiSessionService (persistent sessions)            │
│  └── VertexAiMemoryBankService (cross-session memory)        │
├─────────────────────────────────────────────────────────────┤
│  Root Orchestrator                                           │
│  ├── trend_scanner   → daily.dev MCP (400+ sources)          │
│  ├── gcp_expert      → DeveloperKnowledge MCP + Google Search│
│  ├── blog_drafter    → Dev.to MCP + Nano Banana (images)     │
│  └── growth_promoter → Dev.to MCP (fetch + promote)          │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Description |
|-----------|-------------|
| **Root Orchestrator** | Routes user requests to the right specialist agent |
| **trend_scanner** | Finds trending topics from daily.dev (filters to last 21 days) |
| **gcp_expert** | Technical answers from GCP docs + community |
| **blog_drafter** | Writes posts, generates images, publishes to Dev.to |
| **growth_promoter** | Creates LinkedIn/HN/community promotion drafts |

### MCP Tools

| Tool | Source | Auth |
|------|--------|------|
| **daily.dev MCP** | 400+ aggregated sources | PAT token (Plus subscription) |
| **Dev.to MCP** | Forem API | API key |
| **Hacker News MCP** | Algolia API | None |
| **DeveloperKnowledge MCP** | Google Cloud docs | API key |
| **Nano Banana MCP** | Gemini image generation | GCS bucket |

### Integrations

| Channel | Method |
|---------|--------|
| **Telegram** | Webhook bot — `/trends`, `/promote <url>`, free text chat |
| **ADK Web UI** | Browser-based agent chat |
| **Cloud Scheduler** | Daily 08:00 CET trend alerts to Telegram |
| **Dev.to** | Direct publish via API |

## 📋 Prerequisites

- **Python 3.12+**
- **[uv](https://github.com/astral-sh/uv)** — Fast Python package manager
- **Google Cloud SDK** — Authenticated (`gcloud auth application-default login`)
- **Node.js 20+** — Required for Hacker News MCP tool
- **Terraform** — For infrastructure provisioning

### API Keys Required

| Secret | Source |
|--------|--------|
| `DEVTO_API_KEY` | [dev.to/settings/extensions](https://dev.to/settings/extensions) |
| `DK_API_KEY` | Google Cloud Developer Knowledge |
| `DAILYDEV_API_TOKEN` | [app.daily.dev/settings/api](https://app.daily.dev/settings/api) (Plus required) |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |

## 🛠️ Setup

### 1. Install Dependencies

```bash
git clone <repo-url>
cd dev-signal
uv sync
```

### 2. Configure Environment

Create a `.env` file:

```ini
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
GOOGLE_CLOUD_REGION=europe-west1
GOOGLE_GENAI_USE_VERTEXAI=True
AI_ASSETS_BUCKET=your-bucket-name
AGENT_ENGINE_LOCATION=europe-west1

DEVTO_API_KEY=your_key
DK_API_KEY=your_key
DAILYDEV_API_TOKEN=your_token
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_OWNER_CHAT_ID=your_chat_id
```

### 3. Run Locally

```bash
uv run uvicorn dev_signal_agent.fast_api_app:app --host 0.0.0.0 --port 8080
```

Then open `http://localhost:8080` for the ADK Web UI.

## ☁️ Deployment

### Infrastructure (Terraform)

```bash
cd deployment/terraform
terraform init
terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

Provisions: Cloud Run, Secret Manager, IAM, Artifact Registry, Cloud Scheduler.

### Build & Deploy

```bash
# Build image
gcloud builds submit \
  --tag europe-west1-docker.pkg.dev/PROJECT_ID/dev-signal/dev-signal:latest \
  --region=europe-west1

# Deploy
gcloud run deploy dev-signal \
  --image=europe-west1-docker.pkg.dev/PROJECT_ID/dev-signal/dev-signal:latest \
  --region=europe-west1 \
  --platform=managed
```

Or use the Makefile:

```bash
make docker-deploy
```

### Telegram Webhook Setup

After deployment, set the webhook:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<SERVICE_URL>/telegram/webhook&secret_token=dev-signal-webhook-7x9k2m"
```

## 🤖 Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with available commands |
| `/trends [topic]` | Scan trending topics (optionally filtered) |
| `/promote <url>` | Generate promotion drafts for a Dev.to post |
| Free text | Chat directly with the agent |

After trends are shown, inline buttons let you:
- **Write #N** — Draft a blog post about trend N
- **Mix trends** — Combine multiple trends into one post

## 📂 Project Structure

```
dev-signal/
├── dev_signal_agent/
│   ├── agent.py              # Multi-agent orchestration (root + 4 specialists)
│   ├── fast_api_app.py       # FastAPI server + ADK Web UI + Agent Engine init
│   ├── app_utils/
│   │   └── env.py            # Secret Manager + environment discovery
│   ├── telegram_bot/
│   │   ├── bot.py            # Telegram handlers (/start, /trends, /promote)
│   │   └── routes.py         # Webhook + cron endpoints, background processing
│   └── tools/
│       ├── mcp_config.py     # MCP toolset factory functions
│       ├── dailydev_mcp/     # daily.dev API (trending, discussed, search, tags)
│       ├── devto_mcp/        # Dev.to API (publish, get articles, search)
│       ├── hackernews_mcp/   # Hacker News Algolia API
│       └── nano_banana_mcp/  # Gemini image generation + GCS storage
├── deployment/
│   └── terraform/            # Cloud Run, IAM, Secrets, Scheduler
├── Dockerfile                # Python 3.12 + Node.js 20 (for HN MCP)
├── Makefile                  # Build shortcuts
├── pyproject.toml            # Dependencies (uv)
└── uv.lock                   # Locked dependency versions
```

## 🔧 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Direct ADK Runner** (not HTTP self-calls) | Avoids latency + cold start issues for Telegram |
| **asyncio.create_task()** for agent calls | Returns 200 to Telegram immediately, prevents retries |
| **update_id dedup** | Safety net against Telegram webhook retries |
| **VertexAiSessionService without custom IDs** | Agent Engine generates numeric IDs; we cache per logical name |
| **cpu-boost + scale-to-zero** | Fast cold starts (~8-10s) without paying for idle instances |
| **Date filtering in daily.dev MCP** | Prevents old viral posts from appearing as "recent trends" |
| **Memory Bank** | Cross-session preference persistence (style, topics, past posts) |

## 📊 Monitoring

- **Cloud Run Logs**: `gcloud run services logs read dev-signal --region=europe-west1`
- **Trace Explorer**: View agent reasoning traces in GCP Console
- **Telegram**: Errors are sent directly to the owner chat

## 📝 License

Private project.
