# /// script
# dependencies = ["fastmcp", "httpx"]
# ///
"""Dev.to (Forem) MCP Server — exposes article search and trending retrieval."""

import os
import httpx
from fastmcp import FastMCP

DEVTO_BASE = "https://dev.to/api"
API_KEY = os.environ.get("DEVTO_API_KEY", "")

mcp = FastMCP("devto")


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if API_KEY:
        h["api-key"] = API_KEY
    return h


@mcp.tool()
async def search_articles(query: str, page: int = 1, per_page: int = 10) -> str:
    """
    Search Dev.to articles by keyword/tag.
    Returns title, URL, tags, positive_reactions_count, comments_count, and published date.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{DEVTO_BASE}/articles",
            params={"tag": query, "page": page, "per_page": per_page, "top": 21},
            headers=_headers(),
        )
        resp.raise_for_status()
        articles = resp.json()

    results = []
    for a in articles:
        results.append(
            f"- **{a['title']}**\n"
            f"  URL: {a['url']}\n"
            f"  Tags: {', '.join(a.get('tag_list', []))}\n"
            f"  Reactions: {a.get('positive_reactions_count', 0)} | "
            f"Comments: {a.get('comments_count', 0)}\n"
            f"  Published: {a.get('published_at', 'N/A')}\n"
        )
    return "\n".join(results) if results else "No articles found."


@mcp.tool()
async def get_trending_articles(tag: str = "", page: int = 1, per_page: int = 10) -> str:
    """
    Get trending/top Dev.to articles from the last 21 days.
    Optionally filter by a specific tag (e.g., 'gcp', 'ai', 'cloudrun').
    """
    params = {"page": page, "per_page": per_page, "top": 21}
    if tag:
        params["tag"] = tag

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{DEVTO_BASE}/articles",
            params=params,
            headers=_headers(),
        )
        resp.raise_for_status()
        articles = resp.json()

    results = []
    for a in articles:
        results.append(
            f"- **{a['title']}** by {a.get('user', {}).get('username', 'unknown')}\n"
            f"  URL: {a['url']}\n"
            f"  Tags: {', '.join(a.get('tag_list', []))}\n"
            f"  Reactions: {a.get('positive_reactions_count', 0)} | "
            f"Comments: {a.get('comments_count', 0)}\n"
            f"  Published: {a.get('published_at', 'N/A')}\n"
        )
    return "\n".join(results) if results else "No trending articles found."


@mcp.tool()
async def get_article_comments(article_id: int) -> str:
    """
    Retrieve comments for a specific Dev.to article by its ID.
    Useful for understanding community discussion around a post.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{DEVTO_BASE}/comments",
            params={"a_id": article_id},
            headers=_headers(),        )
        resp.raise_for_status()
        comments = resp.json()

    results = []
    for c in comments:
        user = c.get("user", {}).get("username", "anonymous")
        body = c.get("body_html", c.get("body", ""))[:300]
        results.append(f"- **{user}**: {body}")
    return "\n".join(results[:20]) if results else "No comments found."


@mcp.tool()
async def publish_article(
    title: str,
    body_markdown: str,
    tags: list[str] | None = None,
    published: bool = False,
    series: str | None = None,
    main_image_url: str | None = None,
) -> str:
    """
    Publish (or save as draft) an article to Dev.to.

    Args:
        title: The title of the article.
        body_markdown: Full article content in Markdown format.
        tags: List of up to 4 tags (e.g. ["gcp", "kubernetes", "ai"]).
        published: If True, publishes immediately. If False, saves as draft.
        series: Optional series name to group related posts.
        main_image_url: Optional URL for the article's cover/header image.

    Returns:
        URL of the published/draft article, or error message.
    """
    if not API_KEY:
        return "ERROR: DEVTO_API_KEY not configured. Cannot publish."

    payload = {
        "article": {
            "title": title,
            "body_markdown": body_markdown,
            "published": published,
            "tags": (tags or [])[:4],
        }
    }
    if series:
        payload["article"]["series"] = series
    if main_image_url:
        payload["article"]["main_image"] = main_image_url

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{DEVTO_BASE}/articles",
            json=payload,
            headers=_headers(),
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            url = data.get("url", "")
            status = "PUBLISHED" if published else "DRAFT saved"
            return f"{status}: {url}"
        else:
            return f"ERROR {resp.status_code}: {resp.text[:500]}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
