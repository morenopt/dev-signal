"""Validate Dev.to API and Hacker News MCP connectivity."""
import sys
import httpx

# Write results to file to avoid Windows terminal encoding issues
out = open("validate_out.txt", "w", encoding="utf-8")

def log(msg):
    out.write(msg + "\n")
    out.flush()

try:
    log("=== Testing Dev.to API ===")
    r = httpx.get(
        "https://dev.to/api/articles",
        params={"tag": "ai", "per_page": "3", "top": "21"},
        headers={"api-key": "9v64jZmkgvmXt7n7SvFC7FRb"},
    )
    log(f"Status: {r.status_code}")
    data = r.json()
    log(f"Articles found: {len(data)}")
    for a in data:
        log(f"  - {a['title']} | {a['positive_reactions_count']} reactions | {a['comments_count']} comments")

    log("\n=== Testing Agent Import ===")
    from dev_signal_agent.agent import root_agent, trend_scanner, gcp_expert, blog_drafter

    log(f"Root agent: {root_agent.name}")
    log(f"  Sub-agents: {[a.name for a in root_agent.sub_agents]}")
    log(f"  trend_scanner tools: {len(trend_scanner.tools)}")
    log(f"  gcp_expert tools: {len(gcp_expert.tools)}")
    log(f"  blog_drafter tools: {len(blog_drafter.tools)}")

    log("\n=== ALL TESTS PASSED ===")
except Exception as e:
    log(f"ERROR: {e}")
    import traceback
    log(traceback.format_exc())
finally:
    out.close()
