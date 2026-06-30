from google.adk.agents import Agent, SequentialAgent, ParallelAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import google_search, AgentTool, load_memory_tool, preload_memory_tool
from google.genai import types
from dev_signal_agent.app_utils.env import init_environment
from dev_signal_agent.tools.mcp_config import (
    get_hackernews_mcp_toolset,
    get_devto_mcp_toolset,
    get_dk_mcp_toolset,
    get_nano_banana_mcp_toolset,
)

# == Environment & Model =====================================================
PROJECT_ID, MODEL_LOC, SERVICE_LOC, SECRETS = init_environment()

shared_model = Gemini(
    model="gemini-3-flash-preview",
    vertexai=True,
    project=PROJECT_ID,
    location=MODEL_LOC,
    retry_options=types.HttpRetryOptions(attempts=3),
)

# == Callbacks ================================================================


async def save_session_to_memory_callback(*args, **kwargs) -> None:
    """Persist session history to the Vertex AI memory bank."""
    ctx = kwargs.get("callback_context") or (args[0] if args else None)
    if (
        ctx
        and hasattr(ctx, "_invocation_context")
        and ctx._invocation_context.memory_service
    ):
        await ctx._invocation_context.memory_service.add_session_to_memory(
            ctx._invocation_context.session
        )


async def save_research_and_memory_callback(*args, **kwargs) -> None:
    """Accumulate gcp_expert research iterations + persist to memory bank."""
    ctx = kwargs.get("callback_context") or (args[0] if args else None)
    if not ctx or not hasattr(ctx, "_invocation_context"):
        return
    session = ctx._invocation_context.session
    latest = session.state.get("app:technical_research_findings")
    if latest:
        history = session.state.get("app:technical_research_history", [])
        history.append(latest)
        session.state["app:technical_research_history"] = history
    if ctx._invocation_context.memory_service:
        await ctx._invocation_context.memory_service.add_session_to_memory(session)


async def save_trends_and_memory_callback(*args, **kwargs) -> None:
    """Accumulate trend_scanner iterations + persist to memory bank."""
    ctx = kwargs.get("callback_context") or (args[0] if args else None)
    if not ctx or not hasattr(ctx, "_invocation_context"):
        return
    session = ctx._invocation_context.session
    latest = session.state.get("app:trend_findings")
    if latest:
        history = session.state.get("app:trend_history", [])
        history.append(latest)
        session.state["app:trend_history"] = history
    if ctx._invocation_context.memory_service:
        await ctx._invocation_context.memory_service.add_session_to_memory(session)


# == MCP Toolsets (singletons) ================================================
hn_mcp = get_hackernews_mcp_toolset()
devto_mcp = get_devto_mcp_toolset(api_key=SECRETS.get("DEVTO_API_KEY", ""))
dk_mcp = get_dk_mcp_toolset(api_key=SECRETS.get("DK_API_KEY", ""))
nano_mcp = get_nano_banana_mcp_toolset()

# == Specialist Agents ========================================================

search_agent = Agent(
    name="search_agent",
    model=shared_model,
    instruction=(
        "Execute Google Searches and return raw, structured results "
        "(Title, Link, Snippet)."
    ),
    tools=[google_search],
)

trend_scanner = Agent(
    name="trend_scanner",
    model=shared_model,
    description=(
        "Finds trending questions and high-engagement topics "
        "on Hacker News and Dev.to."
    ),
    output_key="app:trend_findings",
    instruction="""
You are a technical trend research specialist. Identify high-engagement
questions and discussions from the last 3 weeks.

Sources:
- **Hacker News**: cutting-edge technical discussions and startup trends.
- **Dev.to**: practical tutorials and community-driven content.

Steps:
1. **MEMORY CHECK**: Use `load_memory` for the user's past interests.
2. Search HN and Dev.to MCP tools for relevant stories and articles.
3. Filter for posts from the last 21 days.
4. Rank by engagement (points/reactions + comments).
5. For each item provide: direct link, concise summary, engagement stats.
6. **CAPTURE PREFERENCES**: Acknowledge user preferences explicitly.
""",
    tools=[hn_mcp, devto_mcp, load_memory_tool.LoadMemoryTool()],
    after_agent_callback=save_trends_and_memory_callback,
)

gcp_expert = Agent(
    name="gcp_expert",
    model=shared_model,
    description=(
        "Provides accurate, cited technical answers by synthesizing "
        "official GCP documentation with community insights."
    ),
    output_key="app:technical_research_findings",
    instruction="""
You are a Google Cloud Platform documentation expert.
Provide accurate, detailed, and cited answers by synthesizing
official docs with community insights.

For EVERY question, use ALL tools:
1. **Official Docs**: DeveloperKnowledge MCP (`search_documents`).
2. **Community**: HN and Dev.to MCP tools for real-world discussions.
3. **Web**: `search_agent` for recent blogs and tutorials.

Synthesize:
- Start with the official answer from GCP docs.
- Add "Community Insights" from HN, Dev.to, Web Search.
- Cite sources with direct links (URLs) at the end.
- **CAPTURE PREFERENCES**: Acknowledge user preferences explicitly.
""",
    tools=[dk_mcp, AgentTool(search_agent), hn_mcp, devto_mcp],
    after_agent_callback=save_research_and_memory_callback,
)

blog_drafter = Agent(
    name="blog_drafter",
    model=shared_model,
    description=(
        "Writes professional technical blog posts and generates "
        "header images using Nano Banana."
    ),
    output_key="app:blog_draft",
    instruction="""
You are a professional technical blogger at the quality level of a
top-tier consultancy (McKinsey, BCG, Deloitte).

**Available research in session state (auto-populated by pipeline):**
- `app:trend_findings` / `app:trend_history`: Community trends.
- `app:technical_research_findings` / `app:technical_research_history`: Docs research.

Use ALL available research. If none exists, research via `dk_mcp`.

Steps:
1. **MEMORY CHECK**: `load_memory` for style prefs and past posts.
2. **REVIEW**: Read ALL research from state. Verify facts via `dk_mcp`.
3. **DRAFT**: Write an engaging, accurate, actionable blog post with:
   - Clear sections, code snippets, architecture diagrams
   - Community insights from the research
   - "Resources" section with source links
4. **VISUALS**: Ask if user wants a header image. If yes, call
   `generate_image` immediately. You HAVE this capability.
5. **IMAGE REQUESTS**: If user asks for an image, call `generate_image`
   right away. Never refuse. Translate to English prompt and call.
6. **CAPTURE PREFERENCES**: Acknowledge user preferences explicitly.
""",
    tools=[dk_mcp, load_memory_tool.LoadMemoryTool(), nano_mcp],
    after_agent_callback=save_session_to_memory_callback,
)

# == Content Pipeline (deterministic workflow) ================================
#
# Architecture:
#   content_pipeline (SequentialAgent)
#   +-- 1. parallel_research (ParallelAgent)   <-- runs SIMULTANEOUSLY
#   |   +-- trend_scanner   --> output_key: app:trend_findings
#   |   +-- gcp_expert      --> output_key: app:technical_research_findings
#   +-- 2. blog_drafter     --> reads both, writes draft + offers image
#
# Guarantees: research ALWAYS before writing. Deterministic. Fast.

parallel_research = ParallelAgent(
    name="parallel_research",
    description=(
        "Runs community trend analysis AND official documentation "
        "research simultaneously."
    ),
    sub_agents=[trend_scanner, gcp_expert],
)

content_pipeline = SequentialAgent(
    name="content_pipeline",
    description=(
        "Full content creation pipeline for world-class technical blog posts. "
        "Phase 1 (Parallel): Scans HN/Dev.to trends AND researches GCP docs. "
        "Phase 2 (Sequential): Drafts a professional blog post using ALL research. "
        "Phase 3 (Interactive): Offers to generate a header image with Nano Banana. "
        "Use when user wants a COMPLETE blog post with full research backing."
    ),
    sub_agents=[parallel_research, blog_drafter],
)

# == Root Orchestrator ========================================================

root_agent = Agent(
    name="root_orchestrator",
    model=shared_model,
    instruction="""
You are a technical content strategist at a world-class consultancy.
You manage specialists and a fully automated content pipeline.

**YOUR TEAM:**
1. **trend_scanner**: Finds trending topics on HN and Dev.to.
2. **gcp_expert**: Cited technical answers from GCP docs + community.
3. **blog_drafter**: Professional blog posts + image generation.
4. **content_pipeline**: FULL AUTOMATED WORKFLOW (research + write).

**WORKFLOW RULES:**

- **MEMORY**: Use `load_memory` + `preload_memory` at conversation start.
- **CAPTURE PREFERENCES**: Acknowledge user preferences explicitly.

- **Individual tasks** (user asks for ONE thing):
  - Trending topics -> delegate to `trend_scanner`
  - Technical question -> delegate to `gcp_expert`
  - Write/edit a blog draft -> delegate to `blog_drafter`
  - Generate an image -> delegate to `blog_drafter`

- **Full blog post creation** (user wants a COMPLETE post on a topic):
  ALWAYS delegate to `content_pipeline`. It automatically:
    1. Scans HN + Dev.to trends (parallel)
    2. Researches GCP docs + community (parallel)
    3. Drafts blog using ALL research
    4. Offers header image generation

  **CRITICAL**: "write a blog about X", "create a post about Y",
  "full article on Z", "research and write about W" -> `content_pipeline`.
  Do NOT manually chain trend_scanner -> gcp_expert -> blog_drafter.

- **After gcp_expert** answers a standalone question, ask:
  "Would you like me to draft a technical blog post based on this?"
  If yes -> delegate to `blog_drafter` (research already in state).

- Be proactive. Guide: discovery -> research -> content creation.
""",
    tools=[
        load_memory_tool.LoadMemoryTool(),
        preload_memory_tool.PreloadMemoryTool(),
    ],
    after_agent_callback=save_session_to_memory_callback,
    sub_agents=[trend_scanner, gcp_expert, blog_drafter, content_pipeline],
)

app = App(root_agent=root_agent, name="dev_signal_agent")
