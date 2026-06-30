"""Quick test to validate the Dev.to API connection."""
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

async def test_devto_api():
    api_key = os.getenv("DEVTO_API_KEY", "")
    print(f"Testing Dev.to API (key present: {bool(api_key)})...")
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://dev.to/api/articles",
            params={"tag": "ai", "per_page": 3, "top": 7},
            headers={"Accept": "application/json", "api-key": api_key},
        )
        resp.raise_for_status()
        articles = resp.json()
        print(f"Got {len(articles)} articles:")
        for a in articles[:3]:
            title = a["title"]
            reactions = a.get("positive_reactions_count", 0)
            print(f"  - {title} ({reactions} reactions)")
    
    print("\nDev.to API connection OK!")

asyncio.run(test_devto_api())
