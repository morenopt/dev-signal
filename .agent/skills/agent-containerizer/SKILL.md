---
name: agent-containerizer
description: Generates a standard Dockerfile that includes both Python and Node.js environments for AI agents.
---

# agent-containerizer

This skill helps you package your AI agent into a production-ready container. It ensures that both Python (for ADK) and Node.js (for toolsets like `hn-mcp`) are correctly installed and available.

## Usage

Ask Antigravity to:
- "Generate a Dockerfile for my agent"
- "Containerize my project for Cloud Run"
- "Make sure hn-mcp works in my Docker image"

## Container Pattern

The generated Dockerfile includes:
1. **Python 3.12-slim Base**: A lightweight foundation for the agent logic.
2. **Node.js Installation**: Essential for running MCP servers distributed via `npm` or `npx`.
3. **Global Tool Installation**: Hacker News MCP runs via `npx` at runtime — no global install needed.
4. **uv Integration**: Uses the `uv` package manager for fast and reproducible Python dependency installation.
5. **FastAPI Setup**: Configures the container to run the `uvicorn` server on the correct port (8080).

## Dockerfile Template

Refer to the included `resources/Dockerfile` for the standard implementation.
