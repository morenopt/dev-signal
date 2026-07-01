# /// script
# dependencies = ["fastmcp", "httpx"]
# ///
"""daily.dev MCP Server — aggregated tech trends from 400+ sources.

Wraps the daily.dev Public API (https://api.daily.dev/public/v1) to provide
trending posts, most-discussed threads, tag/source feeds, and search across
all sources daily.dev indexes (Hacker News, Dev.to, Medium, Reddit, InfoQ,
GitHub, and hundreds more).

Requires a daily.dev Plus subscription and a Personal Access Token (PAT)
generated at https://app.daily.dev/settings/api.
"""

import os
import httpx
from datetime import datetime, timedelta, timezone
from fastmcp import FastMCP

DAILYDEV_BASE = "https://api.daily.dev/public/v1"
API_TOKEN = os.environ.get("DAILYDEV_API_TOKEN", "").strip()

mcp = FastMCP("dailydev")


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
    return h


def _format_post(p: dict) -> str:
    """Format a single daily.dev post into a readable markdown snippet."""
    title = p.get("title", "Untitled")
    url = p.get("url") or p.get("commentsPermalink", "N/A")
    permalink = p.get("commentsPermalink", "")
    source = p.get("source", {})
    source_name = source.get("name", "unknown") if isinstance(source, dict) else "unknown"
    tags = ", ".join(p.get("tags") or [])
    upvotes = p.get("numUpvotes", 0)
    comments = p.get("numComments", 0)
    read_time = p.get("readTime", "?")
    published = p.get("publishedAt") or p.get("createdAt", "N/A")
    summary = p.get("summary", "")
    if summary and len(summary) > 200:
        summary = summary[:200] + "..."

    return (
        f"- **{title}**\n"
        f"  Source: {source_name} | Tags: {tags}\n"
        f"  URL: {url}\n"
        f"  Discussion: {permalink}\n"
        f"  Upvotes: {upvotes} | Comments: {comments} | Read: {read_time} min\n"
        f"  Published: {published}\n"
        f"  {f'Summary: {summary}' if summary else ''}\n"
    )


def _filter_recent(posts: list[dict], max_age_days: int) -> list[dict]:
    """Filter posts to only include those published within max_age_days."""
    if max_age_days <= 0:
        return posts
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    recent = []
    for p in posts:
        pub_str = p.get("publishedAt") or p.get("createdAt", "")
        if not pub_str:
            continue
        try:
            # daily.dev uses ISO 8601 format
            pub_date = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            if pub_date >= cutoff:
                recent.append(p)
        except (ValueError, TypeError):
            # If date parsing fails, include the post (benefit of doubt)
            recent.append(p)
    return recent


@mcp.tool()
async def get_trending_posts(tags: str = "", limit: int = 20, max_age_days: int = 21) -> str:
    """
    Get trending/popular posts from daily.dev (aggregates 400+ sources
    including Hacker News, Dev.to, Medium, Reddit, and more).

    Args:
        tags: Comma-separated tags to filter by (e.g. "ai,devops,kubernetes").
              Leave empty for general trending.
        limit: Number of posts to return (1-50, default 20).
        max_age_days: Only include posts published within this many days (default 21 = 3 weeks).
                      Set to 0 to disable date filtering.
    """
    # Fetch extra posts to compensate for date filtering
    fetch_limit = min(limit * 3, 50)
    params: dict = {"limit": fetch_limit}
    if tags:
        params["tags"] = tags

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{DAILYDEV_BASE}/feeds/popular",
            params=params,
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    posts = data.get("data", [])
    posts = _filter_recent(posts, max_age_days)[:limit]
    results = [_format_post(p) for p in posts]
    return "\n".join(results) if results else "No trending posts found."


@mcp.tool()
async def get_most_discussed(period: int = 7, tag: str = "", limit: int = 20, max_age_days: int = 21) -> str:
    """
    Get the most discussed posts on daily.dev over a time period.
    Great for finding hot debates and community engagement.

    Args:
        period: Number of days to look back for discussion activity (1-30, default 7).
        tag: Optional tag to filter by (e.g. "ai", "python").
        limit: Number of posts to return (1-50, default 20).
        max_age_days: Only include posts published within this many days (default 21 = 3 weeks).
                      Set to 0 to disable date filtering.
    """
    # Fetch extra posts to compensate for date filtering
    fetch_limit = min(limit * 3, 50)
    params: dict = {"limit": fetch_limit, "period": min(period, 30)}
    if tag:
        params["tag"] = tag

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{DAILYDEV_BASE}/feeds/discussed",
            params=params,
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    posts = data.get("data", [])
    posts = _filter_recent(posts, max_age_days)[:limit]
    results = [_format_post(p) for p in posts]
    return "\n".join(results) if results else "No discussed posts found."


@mcp.tool()
async def get_tag_feed(tag: str, limit: int = 20) -> str:
    """
    Get posts for a specific tag from daily.dev.
    Useful for deep-diving into a particular technology or topic.

    Args:
        tag: The tag to get posts for (e.g. "gcp", "rust", "llm").
        limit: Number of posts to return (1-50, default 20).
    """
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{DAILYDEV_BASE}/feeds/tag/{tag}",
            params={"limit": min(limit, 50)},
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    posts = data.get("data", [])
    results = [_format_post(p) for p in posts]
    return "\n".join(results) if results else f"No posts found for tag '{tag}'."


@mcp.tool()
async def search_posts(query: str, time: str = "week", limit: int = 20) -> str:
    """
    Search daily.dev posts by keyword across all 400+ aggregated sources.

    Args:
        query: Search keywords (e.g. "cloud run scaling", "RAG agents").
        time: Time range — "day", "week", "month", "year", or "all".
        limit: Number of posts to return (1-50, default 20).
    """
    params: dict = {"q": query, "limit": min(limit, 50)}
    if time in ("day", "week", "month", "year", "all"):
        params["time"] = time

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{DAILYDEV_BASE}/search/posts",
            params=params,
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    posts = data.get("data", [])
    results = [_format_post(p) for p in posts]
    return "\n".join(results) if results else f"No posts found for '{query}'."


@mcp.tool()
async def discover_tags(query: str) -> str:
    """
    Search for tags on daily.dev. Useful for finding the right tag names
    before filtering feeds (e.g. is it "k8s" or "kubernetes"?).

    Args:
        query: Partial tag name to search for.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{DAILYDEV_BASE}/search/tags",
            params={"q": query},
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    tags = data.get("data", [])
    if not tags:
        return f"No tags found matching '{query}'."

    results = [f"- `{t.get('name', t)}`" for t in tags]
    return "Available tags:\n" + "\n".join(results)


if __name__ == "__main__":
    mcp.run(transport="stdio")
