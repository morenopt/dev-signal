import os
import sys
from mcp import StdioServerParameters
from google.adk.tools import McpToolset
from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams, StdioConnectionParams


def _get_script_command(path: str) -> tuple[str, list[str]]:
    """
    Determine how to run MCP server scripts.
    In production (Cloud Run / Docker), use the venv Python directly since all
    dependencies are pre-installed via `uv sync`. This avoids uv trying to
    resolve inline script metadata and downloading packages at runtime.
    Locally, use `uv run` for convenience (handles inline deps automatically).
    """
    # Detect if running inside a container (Cloud Run sets K_SERVICE env var)
    if os.environ.get("K_SERVICE") or os.environ.get("RUNNING_IN_CONTAINER"):
        return sys.executable, [path]
    return "uv", ["run", path]


def get_hackernews_mcp_toolset():
    """
    Connects to the Hacker News MCP server.
    Local FastMCP subprocess wrapping the HN Algolia API — no authentication required.
    """
    path = os.path.join("dev_signal_agent", "tools", "hackernews_mcp", "main.py")
    command, args = _get_script_command(path)

    env = {
        **os.environ,
        "LANG": "en_US.UTF-8"
    }

    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=command,
                args=args,
                env=env
            ),
            timeout=120.0
        )
    )


def get_devto_mcp_toolset(api_key: str = ""):
    """
    Connects to the Dev.to MCP server.
    This is a local FastMCP subprocess wrapping the Forem/Dev.to API.
    API key is free: https://dev.to/settings/extensions
    """
    path = os.path.join("dev_signal_agent", "tools", "devto_mcp", "main.py")
    command, args = _get_script_command(path)

    env = {**os.environ, "LANG": "en_US.UTF-8"}
    if api_key:
        env["DEVTO_API_KEY"] = api_key

    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=command,
                args=args,
                env=env
            ),
            timeout=120.0
        )
    )

def get_dk_mcp_toolset(api_key: str = ""):
    """
    Connects to Developer Knowledge (Google Cloud Docs).
    This is a remote MCP server accessed via HTTP.
    """
    headers = {}
    if api_key:
        headers["X-Goog-Api-Key"] = api_key
    else:
        # Fallback to os.environ for local testing if not passed via API
        headers["X-Goog-Api-Key"] = os.getenv("DK_API_KEY", "")

    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url="https://developerknowledge.googleapis.com/mcp",
            headers=headers
        )
    )

def get_nano_banana_mcp_toolset():
    """
    Connects to our local 'Nano Banana' image generator.
    This demonstrates how to wrap a local Python script as an MCP tool.
    """
    path = os.path.join("dev_signal_agent", "tools", "nano_banana_mcp", "main.py")
    command, args = _get_script_command(path)
    bucket = os.getenv("AI_ASSETS_BUCKET") 
    
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=command, 
                args=args, 
                env={**os.environ, "AI_ASSETS_BUCKET": bucket}
            ),
            timeout=600.0 # Image generation can take time
        )
    )
