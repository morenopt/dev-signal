# /// script
# dependencies = ["mcp[cli]", "httpx"]
# ///
"""Hacker News MCP Server — wraps HN Algolia API for story/comment search."""

import httpx
from mcp.server.fastmcp import FastMCP

HN_BASE = "https://hn.algolia.com/api/v1"

mcp = FastMCP("hackernews")


@mcp.tool()
async def search_stories(query: str, num_results: int = 10) -> str:
    """
    Search Hacker News stories by keyword.
    Returns title, URL, points, num_comments, and date for each story.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{HN_BASE}/search",
            params={"query": query, "tags": "story", "hitsPerPage": num_results},
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])

    results = []
    for h in hits:
        title = h.get("title", "Untitled")
        url = h.get("url", f"https://news.ycombinator.com/item?id={h.get('objectID', '')}")
        points = h.get("points", 0)
        comments = h.get("num_comments", 0)
        date = h.get("created_at", "N/A")
        hn_link = f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"
        results.append(
            f"- **{title}**\n"
            f"  URL: {url}\n"
            f"  HN Thread: {hn_link}\n"
            f"  Points: {points} | Comments: {comments}\n"
            f"  Date: {date}\n"
        )
    return "\n".join(results) if results else "No stories found."


@mcp.tool()
async def search_recent_stories(query: str, days: int = 21, num_results: int = 10) -> str:
    """
    Search Hacker News stories from the last N days (default 21).
    Sorted by date, filtered by recency. Great for finding trending discussions.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{HN_BASE}/search_by_date",
            params={
                "query": query,
                "tags": "story",
                "hitsPerPage": num_results,
                "numericFilters": f"created_at_i>{_days_ago_timestamp(days)}",
            },
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])

    results = []
    for h in hits:
        title = h.get("title", "Untitled")
        url = h.get("url", f"https://news.ycombinator.com/item?id={h.get('objectID', '')}")
        points = h.get("points", 0)
        comments = h.get("num_comments", 0)
        date = h.get("created_at", "N/A")
        hn_link = f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"
        results.append(
            f"- **{title}**\n"
            f"  URL: {url}\n"
            f"  HN Thread: {hn_link}\n"
            f"  Points: {points} | Comments: {comments}\n"
            f"  Date: {date}\n"
        )
    return "\n".join(results) if results else "No recent stories found."


@mcp.tool()
async def get_story_comments(story_id: str, num_comments: int = 15) -> str:
    """
    Get comments for a specific Hacker News story by its ID.
    Useful to understand community sentiment and discussion.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{HN_BASE}/search",
            params={
                "tags": f"comment,story_{story_id}",
                "hitsPerPage": num_comments,
            },
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])

    results = []
    for h in hits:
        author = h.get("author", "anonymous")
        text = h.get("comment_text", "")[:300]
        results.append(f"- **{author}**: {text}")
    return "\n".join(results) if results else "No comments found."


def _days_ago_timestamp(days: int) -> int:
    """Return unix timestamp for N days ago."""
    import time
    return int(time.time()) - (days * 86400)


if __name__ == "__main__":
    mcp.run(transport="stdio")
