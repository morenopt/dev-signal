from google.adk.agents import Agent  # noqa: SequentialAgent/ParallelAgent removed
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import google_search, AgentTool, load_memory_tool, preload_memory_tool
from google.genai import types
from dev_signal_agent.app_utils.env import init_environment
from dev_signal_agent.tools.mcp_config import (
    get_hackernews_mcp_toolset,
    get_devto_mcp_toolset,
    get_dailydev_mcp_toolset,
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
# daily.dev aggregates 400+ sources (HN, Dev.to, Medium, Reddit, etc.)
dailydev_mcp = get_dailydev_mcp_toolset(api_token=SECRETS.get("DAILYDEV_API_TOKEN", ""))

# HN and Dev.to kept available for direct access if needed
hn_mcp = get_hackernews_mcp_toolset()
devto_mcp = get_devto_mcp_toolset(api_key=SECRETS.get("DEVTO_API_KEY", ""))

dk_mcp = get_dk_mcp_toolset(api_key=SECRETS.get("DK_API_KEY", ""))
nano_mcp = get_nano_banana_mcp_toolset()

# == Specialist Agents ========================================================

search_agent = Agent(
    name="search_agent",
    model=shared_model,
    instruction="Execute Google Searches and return raw, structured results (Title, Link, Snippet).",
    tools=[google_search],
)

trend_scanner = Agent(
    name="trend_scanner",
    model=shared_model,
    description="Finds trending questions and high-engagement topics across 400+ tech sources via daily.dev.",
    output_key="app:trend_findings",
    instruction="""
You are a technical trend research specialist. Identify high-engagement
questions and discussions from the last 3 weeks.

IMPORTANT: Today's date is dynamically determined at runtime. Only present
posts with a publishedAt date within the last 21 days. If a post's date
is older than 3 weeks, EXCLUDE it from results even if the API returns it.

Source:
- **daily.dev**: aggregates 400+ sources including Hacker News, Dev.to,
  Medium, Reddit, InfoQ, GitHub blogs, and many more.

Steps:
1. **MEMORY CHECK**: Use `load_memory` for the user's past interests.
2. Use `get_trending_posts` for general trending content.
   Use `get_most_discussed` for hot discussions (set period=21 for 3 weeks).
   Use `search_posts` when the user asks about a specific topic.
   Use `get_tag_feed` to deep-dive into a technology.
   Use `discover_tags` to find the right tag names.
3. Rank by engagement (upvotes + comments).
4. For each item provide: direct link, source name, concise summary,
   engagement stats, and tags.
5. **CAPTURE PREFERENCES**: Acknowledge user preferences explicitly.
""",
    tools=[dailydev_mcp, load_memory_tool.LoadMemoryTool()],
    after_agent_callback=save_trends_and_memory_callback,
)

gcp_expert = Agent(
    name="gcp_expert",
    model=shared_model,
    description="Provides accurate, cited technical answers by synthesizing official GCP documentation with community insights.",
    output_key="app:technical_research_findings",
    instruction="""
You are a Google Cloud Platform documentation expert.
Provide accurate, detailed, and cited answers by synthesizing
official docs with community insights.

For EVERY question, use ALL tools:
1. **Official Docs**: DeveloperKnowledge MCP (`search_documents`).
2. **Community**: daily.dev MCP tools for real-world discussions across
   400+ sources (HN, Dev.to, Medium, Reddit, etc.).
3. **Web**: `search_agent` for recent blogs and tutorials.

Synthesize:
- Start with the official answer from GCP docs.
- Add "Community Insights" from daily.dev, Web Search.
- Cite sources with direct links (URLs) at the end.
- **CAPTURE PREFERENCES**: Acknowledge user preferences explicitly.
""",
    tools=[dk_mcp, AgentTool(search_agent), dailydev_mcp],
    after_agent_callback=save_research_and_memory_callback,
)

blog_drafter = Agent(
    name="blog_drafter",
    model=shared_model,
    description="Writes professional technical blog posts, generates images, and publishes to Dev.to.",
    output_key="app:blog_draft",
    instruction="""
You are a professional technical blogger at the quality level of a
top-tier consultancy (McKinsey, BCG, Deloitte).

If the gcp_expert has already run in this session, its latest findings
will be in `app:technical_research_findings`. Use ONLY this latest
research (not the full history) to write the blog post.
If no research exists, use `dk_mcp` to do your own.

Steps:
1. **MEMORY CHECK**: `load_memory` for style prefs and past posts.
2. **REVIEW**: Check `app:technical_research_findings` for research.
   Verify key facts via `dk_mcp`.
3. **DRAFT**: Write an engaging, accurate, actionable blog post with:
   - Clear sections, code snippets, architecture diagrams
   - Community insights from the research
   - "Resources" section with source links
4. **IMAGES**: For each major section, generate an illustrative image
   using `generate_image` with a descriptive English prompt.
   Embed the returned URL in the markdown as `![description](url)`.
5. **PRESENT**: Show the full draft to the user and ask:
   "Want me to publish this to Dev.to? (as draft or live?)"
6. **PUBLISH**: If user approves, call `publish_article` with:
   - title, body_markdown (full post with image URLs embedded)
   - tags (up to 4 relevant tags)
   - published=False for draft, published=True for live
   - main_image_url (the header image URL if generated)
   NEVER publish without explicit user approval.
7. **IMAGE REQUESTS**: If user asks for an image at any point, call
   `generate_image` right away. Never refuse.
8. **CAPTURE PREFERENCES**: Acknowledge user preferences explicitly.
""",
    tools=[dk_mcp, load_memory_tool.LoadMemoryTool(), nano_mcp, devto_mcp],
    after_agent_callback=save_session_to_memory_callback,
)

growth_promoter = Agent(
    name="growth_promoter",
    model=shared_model,
    description="Generates channel-specific promotion drafts for a published Dev.to blog post, adapted to LinkedIn, Hacker News, and daily.dev audiences.",
    output_key="app:promotion_drafts",
    instruction="""
You are a technical content growth specialist. Your job is to take a
published Dev.to blog post and create promotion drafts tailored to
different channels. Each draft must adapt the ANGLE and TONE to the
target audience while linking back to the original Dev.to post.

**GETTING THE POST CONTENT:**
1. Check `app:blog_draft` in session state first (if same session).
2. If the user provides a Dev.to URL, use `get_article` to fetch the
   full post content (title, body, tags, stats).
3. If neither is available, ask the user for the URL.

**CHANNELS & ANGLES:**

1. **LinkedIn** (enterprise decision-makers, architects, CTOs)
   - Angle: Enterprise architecture, resilience, business impact
   - Tone: Professional, thought-leadership, insight-driven
   - Format: 1-2 short paragraphs + key takeaway + link
   - Use bullet points for scanability
   - Include 3-5 relevant hashtags (#CloudArchitecture, #DevOps, etc.)
   - Max ~1300 characters (LinkedIn sweet spot)

2. **Hacker News** (hackers, builders, technical purists)
   - Angle: Technical curiosity, simplicity, clever engineering
   - Tone: Concise, factual, no marketing fluff — HN hates hype
   - Format: Just a compelling TITLE (this is the submission title)
   - Also provide a brief "comment" to post after submission that adds
     context, acknowledges trade-offs, or asks a genuine question
   - Title should spark curiosity without being clickbait
   - NO emojis, NO hashtags

3. **daily.dev / Dev.to community** (developers, platform engineers)
   - Angle: Developer experience, platform engineering, hands-on
   - Tone: Peer-to-peer, practical, community-oriented
   - Format: Short teaser post / comment (3-4 sentences)
   - Focus on what the reader will LEARN or BUILD
   - Include 2-3 relevant tags

**OUTPUT FORMAT:**
Present all 3 drafts clearly separated with headers:

---
## LinkedIn Draft
[draft content]

---
## Hacker News Draft
**Title:** [title]
**First comment:** [comment]

---
## daily.dev / Community Draft
[draft content]

---

**IMAGES:**
- When fetching the post, check if it contains images (markdown `![...](url)`).
- For LinkedIn: include the most impactful image (architecture diagram or
  header image) — LinkedIn posts with images get 2x engagement.
- For HN: do NOT include images (text-only submission).
- For daily.dev/community: include an image if it adds technical clarity
  (e.g. architecture diagram), skip decorative images.

**RULES:**
- NEVER auto-post. These are MANUAL drafts for the user to review and post.
- Always include the Dev.to post URL in each draft.
- ALL drafts must be written in English.
- Use `load_memory` to check the user's past promotion preferences.
""",
    tools=[devto_mcp, load_memory_tool.LoadMemoryTool()],
    after_agent_callback=save_session_to_memory_callback,
)

# == Root Orchestrator ========================================================

root_agent = Agent(
    name="root_orchestrator",
    model=shared_model,
    instruction="""
You are a technical content strategist. You manage four specialists.
Delegate to the RIGHT one based on what the user asks. Do ONE thing at a time.

**YOUR SPECIALISTS:**
1. `trend_scanner` - Finds trending topics across 400+ sources via daily.dev.
   Use when: user asks "what's trending", "find discussions about X"
2. `gcp_expert` - Technical answers from GCP docs + community.
   Use when: user asks a technical question or wants research on a topic.
3. `blog_drafter` - Writes blog posts + generates images with Nano Banana.
   Use when: user wants a blog post written OR an image generated.
4. `growth_promoter` - Creates promotion drafts for LinkedIn, HN, daily.dev.
   Use when: user says "promote", "grow", "share", "create visibility",
   or asks for promotion drafts after a blog post is published.

**RULES:**
- **MEMORY**: Use `load_memory` at conversation start.
- Delegate to ONE specialist at a time. Do NOT chain them automatically.
- After `blog_drafter` publishes, ask: "Want me to create promotion drafts?"
- Let the USER drive the flow. Don't auto-trigger the full pipeline.
- For greetings or simple questions, answer directly.
""",
    tools=[
        load_memory_tool.LoadMemoryTool(),
        preload_memory_tool.PreloadMemoryTool(),
    ],
    after_agent_callback=save_session_to_memory_callback,
    sub_agents=[trend_scanner, gcp_expert, blog_drafter, growth_promoter],
)

app = App(root_agent=root_agent, name="dev_signal_agent")
