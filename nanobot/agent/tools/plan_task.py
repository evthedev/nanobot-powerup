"""plan_task tool — smart LLM (Gemini 3 Flash) for planning AND evaluating complex tasks.

Two modes:
  - plan:     produce a concrete, batched execution plan before any work begins
  - evaluate: after drafting, check the draft against the original criteria and
              return which criteria failed + targeted retry steps

Architecture:
  plan_task(mode="plan")     → structured plan JSON with criteria + batched steps
  execute steps (GPT-4o-mini) → carries out grunt work
  plan_task(mode="evaluate") → verdict + failed criteria + retry instructions
  retry failed steps (optional) → targeted follow-up
  write_response → final complete output
"""

import json
import re
from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.agent.subagent import SubagentManager

# Routed through OpenRouter (same provider as the main agent — no separate connection needed).
# gemini-3-flash-preview: fast and capable, replaces Sonnet for plan + evaluate calls.
_PLANNER_MODEL = "google/gemini-3-flash-preview"

# ---------------------------------------------------------------------------
# Plan prompt
# ---------------------------------------------------------------------------
_PLAN_SYSTEM_PROMPT = """\
You are a task planner. Your job is to produce a concrete, executable plan for a
specific user request — before any work is done.

The plan is returned to the main agent, which will execute it step by step by calling
tools. You do NOT call any tools yourself — you only plan.

Output ONLY valid JSON in the exact schema below. No prose, no markdown fences.

Schema:
{
  "task_type": "<short identifier>",
  "success_criteria": [
    "<specific verifiable condition the final response must satisfy>",
    ...
  ],
  "steps": [
    {
      "id": "step_1",
      "batch": true,
      "tools": [
        {
          "tool": "<exact tool name>",
          "args": { "<param>": "<value>" }
        }
      ],
      "why": "<why this batch is needed>"
    },
    ...
  ],
  "quality_gate": "<what to check before sending — reference specific criteria by number>"
}

════════════════════════════════════════════════════════
SCREENSHOT ARCHITECTURE — READ THIS FIRST
════════════════════════════════════════════════════════

Screenshots are the ONLY proof the agent did not hallucinate a specific claim.
A screenshot of a search results page (DuckDuckGo/Bing link lists) does NOT verify a
factual claim — it only shows that a search query was typed. It is NOT acceptable as evidence.

TWO TYPES OF SCREENSHOTS EXIST. Use the right one for each claim:

TYPE A — SEARCH-RESULTS SCREENSHOTS (valid ONLY for prices and availability):
  The search results page itself shows the answer inline as price cards/snippets.
  Use for: flight prices, hotel availability/rates, ticket prices
  ✅ DuckDuckGo for flights: https://duckduckgo.com/?q=cheap+flights+{ORIGIN}+to+{DEST}+{MONTH+YEAR}+AUD&ia=web
  ✅ Booking.com for hotels: https://www.booking.com/searchresults.html?ss={LOCATION}&checkin=YYYY-MM-DD&checkout=YYYY-MM-DD&group_adults=1&no_rooms=1&order=price
  ✅ DuckDuckGo for tickets: https://duckduckgo.com/?q={EVENT}+{DATE}+tickets+buy&ia=web
  wait_seconds: 3 (flights/tickets), 6 (hotels)
  ❌ NEVER airline sites or skyscanner.com — they show empty booking forms

TYPE B — SOURCE-PAGE SCREENSHOTS (required for ALL factual claims about specific things):
  The screenshot must show the ACTUAL PAGE that contains the information — not a link list.
  A link list proves nothing. The source page proves the fact exists at that source.
  Use for: named places, venues, restaurants, attractions, products, events, reviews, news

  Source page priority order (use highest available):
    1. Wikipedia:   https://en.wikipedia.org/wiki/{Place_Name_With_Underscores}
    2. TripAdvisor: https://www.tripadvisor.com/Search?q={place+name} (wait 4s)
    3. Official site: whatever the web_search returns as the top result
    4. Bing (NOT DuckDuckGo) news article: https://www.bing.com/news/search?q={claim}

  For places/venues/attractions with a Wikipedia article:
    ✅ https://en.wikipedia.org/wiki/Dadaepo_Beach → shows the beach exists with description
    ✅ https://en.wikipedia.org/wiki/Gamcheon_Culture_Village → confirms the village
    ❌ https://duckduckgo.com/?q=Dadaepo+Beach → just a list of links, proves nothing

  For restaurants, events, products without a Wikipedia article:
    Plan the step as: screenshot_pages with url="TOP_RESULT_FOR:<web_search query>"
    The agent will execute the web_search first, extract the top URL, then screenshot it.

  For reviews:
    ✅ https://www.reddit.com/search/?q={query}&sort=relevance (actual Reddit posts)
    ✅ https://www.trustpilot.com/review/{company-slug} (actual review page)

🚫 GOOGLE IS BANNED — detects headless browsers and shows CAPTCHA. NEVER use google.com.
🚫 DuckDuckGo/Bing search results CANNOT verify factual claims. Only source pages can.

════════════════════════════════════════════════════════
SCREENSHOT BATCHING — HARD LIMIT: 5 PAGES PER CALL
════════════════════════════════════════════════════════

screenshot_pages accepts MAXIMUM 5 pages per call.
For more than 5 locations, split into MULTIPLE calls in the SAME batch step — they run in
parallel, so there's no speed or time penalty.

Example — 15 named locations → step_2 has 3 simultaneous screenshot_pages calls:
  call 1: {"tool":"screenshot_pages","args":{"slug":"locs-a","pages":[loc1,loc2,loc3,loc4,loc5]}}
  call 2: {"tool":"screenshot_pages","args":{"slug":"locs-b","pages":[loc6,loc7,loc8,loc9,loc10]}}
  call 3: {"tool":"screenshot_pages","args":{"slug":"locs-c","pages":[loc11,loc12,loc13,loc14,loc15]}}

NEVER omit locations by reducing to fewer calls. EVERY named location needs its own screenshot.

════════════════════════════════════════════════════════
STEP STRUCTURE — MANDATORY FOR TASKS WITH SCREENSHOTS
════════════════════════════════════════════════════════

For tasks with Type B screenshots (places, events, products, reviews), use 3 research steps:

  step_1 (batch): ALL web_search calls + ALL Type A screenshots (prices/availability)
    + exec trip-mapper for travel itineraries (see TRAVEL ITINERARY RULES below)
    → web_search returns URLs of actual source pages for the next step

  step_2 (batch): ALL Type B source-page screenshots
    → Uses specific URLs: Wikipedia URLs where known, or "TOP_RESULT_FOR:<query>" where not
    → Agent extracts top URLs from step_1 search results and screenshots those actual pages
    → For N named locations: generate ceil(N/5) separate screenshot_pages calls in this step
    → Each call covers a different group of 5 locations

  step_3: plan_task(mode="evaluate", ...)

  step_4: write_response

For tasks with ONLY prices/availability (no factual claims about places/things):
  step_1 (batch): web_search + Type A screenshots
  step_2: evaluate
  step_3: write_response

Rules:
- BATCH aggressively — all independent tool calls in ONE step with "batch": true
- The SECOND-TO-LAST step is always evaluate_result:
  {"id":"evaluate_result","batch":false,"tools":[{"tool":"plan_task",
   "args":{"mode":"evaluate","criteria_list":"<numbered criteria>",
   "draft_response":"<the draft you wrote>"}}],
   "why":"Evaluate draft against success criteria before sending"}
- The FINAL step is always write_response:
  {"id":"write_response","batch":false,"tools":[],
   "why":"Write complete response, embed all screenshots, fix any failed criteria."}

════════════════════════════════════════════════════════
TRAVEL ITINERARY RULES — MANDATORY
════════════════════════════════════════════════════════

For any travel itinerary with 3+ distinct visit locations:

1. TRIP MAPPER — always add to step_1 batch alongside web_search calls:
   {"tool":"exec","args":{"command":"python3 ~/.nanobot/workspace/skills/trip-mapper/trip-mapper.py \"Location 1, City\" \"Location 2, City\" \"Location 3, City\" ..."}}
   Use specific names with city (e.g. "Haeundae Beach, Busan" — never just "Haeundae").
   The output contains a ready-to-embed markdown image line and a Google Maps link line —
   copy both VERBATIM into your response. Do NOT use the label names (IMAGE_URL, URL) as values.
   Add to success criteria: "Trip map image embedded + clickable Google Maps link included".

2. PER-LOCATION SCREENSHOTS — count all named locations in the itinerary:
   Every day section has named attractions, restaurants, venues → count them ALL.
   Generate enough screenshot_pages calls in step_2 to cover every single one (max 5 per call).
   Example: 12-day itinerary with 20 named locations → 4 screenshot_pages calls in step_2 batch.
   Each call uses a slug like "day1-3", "day4-6", "day7-9", "day10-12".

3. SUCCESS CRITERIA for screenshots must enumerate the expected count:
   GOOD: "TYPE B source-page screenshot for each of the 20 named locations (minimum 20 screenshots)"
   BAD:  "screenshots for key venues" — too vague, evaluator cannot count

════════════════════════════════════════════════════════
SUCCESS CRITERIA RULES
════════════════════════════════════════════════════════

- Must be SPECIFIC and VERIFIABLE — not vague ("good quality" is banned)
- 5–8 criteria
- The screenshot criterion MUST name every category and specify TYPE A or TYPE B:
  GOOD: "TYPE B source-page screenshot for each named venue (Wikipedia or TripAdvisor page
         showing the actual place), PLUS TYPE A search-result screenshot for flight prices
         and hotel availability"
  BAD:  "all screenshots embedded" — too vague, evaluator cannot check coverage

Available tools: web_search, web_fetch, screenshot_pages, reddit_search, trustpilot_search,
read_file, write_file, exec, spawn, plan_task

Tool signatures:
- web_search(query: str) → returns title, snippet, and URL for each result
- screenshot_pages(slug: str, pages: [{url, label, wait_seconds}]) → content + image URLs
  Special URL value: "TOP_RESULT_FOR:<web_search query>" → agent replaces with actual URL
- reddit_search(query: str, limit: int) → reddit posts
- trustpilot_search(query: str, ...) → reviews
- plan_task(mode: str, ...) → plan or evaluation

For travel tasks: include read_file(path="memory/MEMORY.md") in step_1.
"""

# ---------------------------------------------------------------------------
# Evaluate prompt
# ---------------------------------------------------------------------------
_EVALUATE_SYSTEM_PROMPT = """\
You are a strict quality evaluator. Your job is to check a draft response against
a numbered list of success criteria and return a machine-readable JSON verdict.

Output ONLY valid JSON. No prose, no markdown fences.

Schema:
{
  "verdict": "pass" | "retry",
  "summary": "<one sentence overall assessment>",
  "results": [
    {
      "criterion_number": 1,
      "criterion": "<verbatim criterion text>",
      "pass": true | false,
      "reason": "<why it passes or fails — be specific>",
      "retry_tool": "<tool name if retry needed, else null>",
      "retry_args": { "<param>": "<value>" }
    },
    ...
  ]
}

════════════════════════════════════════════════════════
SCREENSHOT QUALITY RULES — CRITICAL
════════════════════════════════════════════════════════

Two types of screenshots exist. You must distinguish them:

TYPE A — SEARCH-RESULTS PAGE (DuckDuckGo, Bing link lists):
  ONLY acceptable for: flight prices, hotel rates, ticket prices
  Reason: price cards and snippets appear inline in search results — the search page IS the evidence
  FAILS for: named places, venues, restaurants, attractions, products, specific events, reviews
  A link list does NOT confirm a factual claim — it only confirms a search was performed

TYPE B — SOURCE PAGE (Wikipedia, TripAdvisor, official site, Reddit thread, Trustpilot):
  REQUIRED for: any specific named thing (place, venue, restaurant, product, event, review)
  The screenshot must show the actual page that CONTAINS the information about the claim
  A Wikipedia page about a beach VERIFIES the beach exists and shows its characteristics
  A DuckDuckGo search for "Dadaepo Beach" does NOT verify the beach — it's just links

SCREENSHOT AUDIT is prepended to every evaluation. Use it to assess coverage AND quality.

For each named place/venue/attraction/product/event in the draft:
  - If the screenshot URL contains "duckduckgo.com" or "bing.com/search" → FAIL
    Reason: "Search results page does not verify this claim. Retry with Wikipedia or TripAdvisor
    source page for [specific place name]."
  - If the screenshot URL is a source page (en.wikipedia.org, tripadvisor.com, official site) → PASS
  - If no screenshot exists → FAIL

For prices (flights, hotels, tickets):
  - DuckDuckGo/Bing search result screenshots ARE acceptable (snippets show prices)
  - Booking.com search results ARE acceptable (hotel cards shown)

════════════════════════════════════════════════════════
TRAVEL ITINERARY SCREENSHOT COVERAGE
════════════════════════════════════════════════════════

For travel itinerary drafts: extract ALL named locations (attractions, restaurants, hotels,
venues, beaches, temples, cultural sites, transport hubs mentioned as visit points).

1. Count them: N named locations.
2. Count screenshots from SCREENSHOT AUDIT: M screenshots.
3. If M < N → FAIL the screenshot criterion.
   Reason must list the SPECIFIC missing locations by name, e.g.:
   "12 of 20 named locations lack screenshots. Missing: HYBE Building, Gyeongbokgung Palace,
    Baekyang Elementary, Mandeok Village, BEXCO, Gamcheon Culture Village, ..."
   Retry: screenshot_pages for the missing locations (up to 5 per call).
4. Also check: trip map image embedded AND Google Maps link present → FAIL if missing.

════════════════════════════════════════════════════════
COVERAGE RULES
════════════════════════════════════════════════════════

- "pass" verdict only if ALL criteria pass
- "retry" verdict if ANY criterion fails
- Be strict — vague data (e.g. "prices may vary") fails an "actual price in AUD" criterion

For each FAILED screenshot criterion, provide specific retry instructions:
  - Named place without source-page screenshot →
      retry_tool: "screenshot_pages"
      retry_args: {"slug": "...", "pages": [{"url": "https://en.wikipedia.org/wiki/{Place_Name}",
                   "label": "...", "wait_seconds": 4}]}
  - Named restaurant/venue without source page →
      retry_tool: "screenshot_pages"
      retry_args: {"slug": "...", "pages": [{"url": "https://www.tripadvisor.com/Search?q={name}",
                   "label": "...", "wait_seconds": 4}]}
  - Missing price screenshot →
      retry_tool: "screenshot_pages" with DuckDuckGo price search URL
  - Missing factual data entirely →
      retry_tool: "web_search" with specific query

🚫 NEVER suggest google.com URLs — Google shows CAPTCHA to headless browsers.
"""


class PlanTaskTool(Tool):
    """
    Two-mode tool backed by Gemini 3 Flash (via OpenRouter, same connection as main agent):

    mode="plan" (default):
      Defines a structured execution plan for a complex task. Returns success_criteria,
      batched steps with real tool args, and a quality_gate. Call this FIRST for any
      complex multi-step request (travel, reviews, research). The plan always includes an
      evaluate_result step followed by write_response.

    mode="evaluate":
      After drafting a response, evaluates it against the original success criteria.
      Returns pass/fail per criterion and targeted retry instructions for any failures.
      The main agent should retry failed criteria before sending the final response.

    The loop enforces evaluation: if the agent tries to send a final response after
    calling plan but without calling evaluate, the response is blocked and the agent
    is forced to evaluate first.
    """

    def __init__(self, provider: "LLMProvider", subagent_manager: "SubagentManager | None" = None):
        self._provider = provider
        self._subagent_manager = subagent_manager  # used to route LLM calls through subagent log
        # State used by the loop to enforce the evaluation gate
        self._pending_criteria_json: str | None = None  # set on plan, cleared on evaluate
        self._evaluate_count: int = 0  # number of evaluate calls this turn
        self._last_failed: list[dict] = []  # failed criteria from the most recent evaluate
        self._disclosure_injected: bool = False  # True once the disclosure gate has fired

    # ------------------------------------------------------------------
    # Evaluation gate helpers (called by the agent loop)
    # ------------------------------------------------------------------
    def has_pending_evaluation(self) -> bool:
        """True if plan was created but evaluation hasn't been called yet."""
        return self._pending_criteria_json is not None

    def get_pending_criteria_json(self) -> str:
        """Return the criteria JSON string from the last plan call."""
        return self._pending_criteria_json or "[]"

    def reset_turn(self) -> None:
        """Reset per-turn state. Called at the start of each new message."""
        self._pending_criteria_json = None
        self._evaluate_count = 0
        self._last_failed = []
        self._disclosure_injected = False

    def get_last_failed(self) -> list[dict]:
        """Return failed criteria from the most recent evaluate call."""
        return self._last_failed

    def mark_disclosure_injected(self) -> None:
        """Mark that the disclosure gate has already fired this turn."""
        self._disclosure_injected = True

    def disclosure_already_injected(self) -> bool:
        """True if the disclosure gate already fired — don't inject again."""
        return self._disclosure_injected

    def evaluation_limit_reached(self, max_evaluations: int = 2) -> bool:
        """True if the agent has already evaluated the maximum allowed times."""
        return self._evaluate_count >= max_evaluations

    @property
    def name(self) -> str:
        return "plan_task"

    @property
    def description(self) -> str:
        return (
            "Two modes: "
            "(1) mode='plan' — uses a smart LLM to produce a structured execution plan "
            "(success criteria, batched steps with real tool args, quality gate). "
            "Call this FIRST for travel itineraries, reviews, or any multi-step research. "
            "(2) mode='evaluate' — checks a draft response against success criteria, returns "
            "pass/fail per criterion and targeted retry instructions. Call this BEFORE sending "
            "your final response to ensure all criteria are satisfied."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["plan", "evaluate"],
                    "description": (
                        "'plan' to generate an execution plan before any work. "
                        "'evaluate' to validate a draft response against criteria."
                    ),
                },
                "goal": {
                    "type": "string",
                    "description": (
                        "[plan mode] The user's full request including all details "
                        "(destination, dates, budget, preferences, etc.)."
                    ),
                },
                "task_type": {
                    "type": "string",
                    "description": (
                        "[plan mode] Category: 'travel_itinerary', 'product_review', "
                        "'event_research', 'comparison', 'news_summary', etc."
                    ),
                },
                "available_tools": {
                    "type": "string",
                    "description": (
                        "[plan mode] Comma-separated tools available for execution. "
                        "Example: 'web_search, screenshot_pages, reddit_search'"
                    ),
                },
                "criteria_list": {
                    "type": "string",
                    "description": (
                        "[evaluate mode] The numbered success criteria list exactly as "
                        "returned by the plan step (copy from the plan output)."
                    ),
                },
                "draft_response": {
                    "type": "string",
                    "description": (
                        "[evaluate mode] The full draft response to evaluate. "
                        "Include all content the user will see."
                    ),
                },
            },
            "required": ["mode"],
        }

    async def execute(  # pylint: disable=arguments-differ
        self,
        mode: str = "plan",
        goal: str = "",
        task_type: str = "general",
        available_tools: str = "web_search, screenshot_pages, reddit_search, trustpilot_search, web_fetch",
        criteria_list: str = "",
        draft_response: str = "",
        **kwargs: Any,
    ) -> str:
        if mode == "evaluate":
            if self._evaluate_count >= 2:
                logger.info("plan_task[evaluate]: ⛔ max evaluations reached ({}) — skipping, send response as-is", self._evaluate_count)
                if self._last_failed:
                    failed_lines = "\n".join(
                        f"  - Criterion #{r.get('criterion_number')}: {r.get('criterion', '')}\n"
                        f"    Reason: {r.get('reason', '')}"
                        for r in self._last_failed
                    )
                    return (
                        "⚠️ Evaluation limit reached (2 attempts). Send your response now.\n\n"
                        "IMPORTANT: You must be transparent with the user about these gaps that "
                        "could not be resolved after 2 attempts:\n\n"
                        f"{failed_lines}\n\n"
                        "Acknowledge each gap explicitly in your response (e.g. 'Note: I could not "
                        "confirm specific flight numbers — please verify on the airline website')."
                    )
                return (
                    "⚠️ Evaluation limit reached (2 attempts). "
                    "Send your best response now — do not call evaluate again."
                )
            return await self._evaluate(criteria_list, draft_response)
        return await self._plan(goal, task_type, available_tools)

    # ------------------------------------------------------------------
    # Internal LLM call — routed through SubagentManager so it appears
    # in the subagent log panel.  Falls back to direct provider call if
    # the manager is not wired up.
    # ------------------------------------------------------------------
    async def _llm_call(self, label: str, system_prompt: str, user_prompt: str,
                        max_tokens: int = 2048, temperature: float = 0.1) -> str:
        if self._subagent_manager is not None:
            return await self._subagent_manager.run_sync(
                label=label,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=_PLANNER_MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        # Fallback: direct call (no subagent logging)
        response = await self._provider.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=None,
            model=_PLANNER_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.content or ""

    # ------------------------------------------------------------------
    # Plan mode
    # ------------------------------------------------------------------
    def _enforce_travel_screenshot_batching(self, steps: list[dict]) -> list[dict]:
        """Post-process plan steps: split any screenshot_pages call with >5 pages into
        multiple batched calls of max 5. Also warn if step_2 has only 1 screenshot_pages
        call for a travel itinerary.

        This is a programmatic safeguard because the LLM frequently generates a single
        screenshot_pages call even when the itinerary has 15-20 named locations.
        """
        import math
        result = []
        for step in steps:
            if not step.get("batch"):
                result.append(step)
                continue

            new_tools: list[dict] = []
            for tool in step.get("tools", []):
                if tool.get("tool") != "screenshot_pages":
                    new_tools.append(tool)
                    continue
                pages = tool.get("args", {}).get("pages", [])
                slug = tool.get("args", {}).get("slug", "locations")
                if len(pages) <= 5:
                    new_tools.append(tool)
                    continue
                # Split into batches of 5
                batches = [pages[i:i+5] for i in range(0, len(pages), 5)]
                logger.info(
                    "plan_task[plan]: ⚡ splitting screenshot_pages '{}' ({} pages) into {} calls",
                    slug, len(pages), len(batches)
                )
                for idx, batch in enumerate(batches):
                    new_tools.append({
                        "tool": "screenshot_pages",
                        "args": {"slug": f"{slug}-{idx+1}", "pages": batch},
                    })
            result.append({**step, "tools": new_tools})
        return result

    async def _plan(self, goal: str, task_type: str, available_tools: str) -> str:
        logger.info("plan_task[plan]: ▶ planning '{}' using {}", task_type, _PLANNER_MODEL)
        # Reset any prior plan state for this turn
        self._pending_criteria_json = None

        # Inject travel-specific constraint directly into the prompt so the LLM sees it.
        # The system prompt alone isn't sufficient — LLMs consistently generate 1 call.
        travel_constraint = ""
        if task_type == "travel_itinerary":
            travel_constraint = (
                "\n\n⚠️ MANDATORY TRAVEL RULE — step_2 MUST contain MULTIPLE screenshot_pages calls:\n"
                "- A 12-day trip has ~20 named locations → MINIMUM 4 screenshot_pages calls in step_2\n"
                "- Each call: max 5 pages, unique slug (day1-3, day4-6, day7-9, day10-12)\n"
                "- NEVER generate only 1 screenshot_pages call for a multi-day itinerary\n"
                "- This is enforced programmatically — the plan will be rejected if violated\n"
            )

        prompt = (
            f"Task type: {task_type}\n\n"
            f"User request:\n{goal}\n\n"
            f"Available tools: {available_tools}\n\n"
            f"Define the execution plan."
            f"{travel_constraint}"
        )

        try:
            raw_content = await self._llm_call(
                label=f"plan:{task_type}",
                system_prompt=_PLAN_SYSTEM_PROMPT,
                user_prompt=prompt,
                max_tokens=2048,
                temperature=0.2,
            )

            raw = raw_content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            plan = json.loads(raw)
            criteria = plan.get("success_criteria", [])
            steps = plan.get("steps", [])
            quality_gate = plan.get("quality_gate", "")

            # Programmatically enforce screenshot batching for travel itineraries
            if task_type == "travel_itinerary":
                steps = self._enforce_travel_screenshot_batching(steps)
                plan["steps"] = steps

            logger.info(
                "plan_task[plan]: ✅ {} criteria, {} steps",
                len(criteria),
                len(steps),
            )
            for i, c in enumerate(criteria, 1):
                logger.info("  criterion {}: {}", i, c)
            for s in steps:
                tool_names = [t.get("tool") for t in s.get("tools", [])]
                logger.info("  step [{}] batch={} tools={} — {}", s.get("id"), s.get("batch"), tool_names, s.get("why", "")[:80])

            # Set pending evaluation state — loop will block final response until cleared
            self._pending_criteria_json = json.dumps(criteria)

            lines = [
                f"## Execution Plan — {plan.get('task_type', task_type)}\n\n",
                "### ✅ Success Criteria\n",
                "Your response MUST satisfy ALL of these before sending:\n\n",
            ]
            for i, c in enumerate(criteria, 1):
                lines.append(f"{i}. {c}\n")

            # Store criteria as JSON block for evaluate_result step
            criteria_json = json.dumps(criteria)
            lines.append(f"\n**CRITERIA_JSON** (copy this for evaluate_result):\n`{criteria_json}`\n")

            lines.append("\n### 📋 Steps\n\n")
            for s in steps:
                batch_flag = "⚡ BATCH (call all tools simultaneously)" if s.get("batch") else "🔁 sequential"
                lines.append(f"**{s.get('id', '?')}** [{batch_flag}]\n")
                lines.append(f"Why: {s.get('why', '')}\n")
                tools_list = s.get("tools", [])
                if tools_list:
                    lines.append("Tools:\n")
                    for t in tools_list:
                        args_str = json.dumps(t.get("args", {}), ensure_ascii=False)
                        lines.append(f"  - `{t.get('tool', '?')}` args: `{args_str}`\n")
                else:
                    lines.append("  *(no tool calls — write the response)*\n")
                lines.append("\n")

            lines.append(f"### 🔍 Quality Gate\n{quality_gate}\n\n")
            lines.append(
                "**IMPORTANT**: Before sending your response:\n"
                "1. Write a draft\n"
                "2. Call `plan_task(mode='evaluate', criteria_list=<CRITERIA_JSON above>, "
                "draft_response=<your draft>)`\n"
                "3. Fix any criteria flagged as failed\n"
                "4. Only then send the final response\n"
            )

            return "".join(lines)

        except json.JSONDecodeError as exc:
            logger.warning("plan_task[plan]: JSON parse failed ({}), returning raw", exc)
            return f"## Execution Plan\n\n{raw_content or '(empty)'}"  # type: ignore[possibly-undefined]

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("plan_task[plan]: failed with {}", exc)
            return (
                f"plan_task failed ({exc}). Proceed without a formal plan — "
                f"but ensure your response is complete and verifiable before sending."
            )

    # ------------------------------------------------------------------
    # Evaluate mode
    # ------------------------------------------------------------------
    async def _evaluate(self, criteria_list: str, draft_response: str) -> str:
        logger.info("plan_task[evaluate]: ▶ checking draft against criteria using {}", _PLANNER_MODEL)
        logger.info("plan_task[evaluate]: draft length={}, preview: {}", len(draft_response), draft_response[:200])

        if not criteria_list.strip():
            return "⚠️ evaluate skipped — no criteria_list provided. Proceed with caution."
        if not draft_response.strip() or len(draft_response) < 100:
            return (
                "⚠️ evaluate failed — draft_response is empty or too short. "
                "You must pass your COMPLETE draft itinerary as draft_response, not a placeholder. "
                "Write the full response first, then call evaluate with that content."
            )
        if "<your" in draft_response.lower() or "placeholder" in draft_response.lower():
            return (
                "⚠️ evaluate failed — draft_response contains a placeholder instead of real content. "
                "Write the actual complete response first, then pass it as draft_response."
            )

        # Screenshot audit — count and list every embedded image in the draft.
        # Prepended to the evaluator prompt so it can verify coverage without re-reading prose.
        screenshot_refs = re.findall(r'!\[.*?\]\(.*?\)', draft_response)
        screenshot_audit = (
            f"SCREENSHOT AUDIT: The draft contains {len(screenshot_refs)} embedded screenshot(s).\n"
            + (("\n".join(f"  - {s}" for s in screenshot_refs) + "\n\n") if screenshot_refs else "  (none)\n\n")
        )
        logger.info("plan_task[evaluate]: screenshots in draft: {}", len(screenshot_refs))

        # Truncate draft to avoid exceeding context — keep generous limit so full itineraries
        # (10+ days, multiple sections) are evaluated in their entirety.
        draft_truncated = draft_response[:14000] + ("…[truncated]" if len(draft_response) > 14000 else "")
        prompt = (
            f"{screenshot_audit}"
            f"Success criteria:\n{criteria_list}\n\n"
            f"Draft response to evaluate (may be truncated):\n{draft_truncated}\n\n"
            f"Check each criterion. Return the JSON verdict."
        )

        try:
            raw_content = await self._llm_call(
                label="evaluate",
                system_prompt=_EVALUATE_SYSTEM_PROMPT,
                user_prompt=prompt,
                max_tokens=2048,
                temperature=0.1,
            )

            raw = raw_content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            result = json.loads(raw)
            verdict = result.get("verdict", "pass")
            summary = result.get("summary", "")
            results = result.get("results", [])

            passed = [r for r in results if r.get("pass")]
            failed = [r for r in results if not r.get("pass")]

            # Clear pending state — evaluation gate is now satisfied
            self._pending_criteria_json = None
            self._evaluate_count += 1
            self._last_failed = failed  # persist so limit-reached message can report them

            logger.info(
                "plan_task[evaluate]: ✅ verdict={}, passed={}/{}, failed={}",
                verdict,
                len(passed),
                len(results),
                len(failed),
            )
            for r in passed:
                logger.info("  ✅ #{} {}", r.get("criterion_number"), str(r.get("criterion", ""))[:80])
            for r in failed:
                logger.info("  ❌ #{} {} — {}", r.get("criterion_number"), str(r.get("criterion", ""))[:60], r.get("reason", "")[:80])

            lines = [
                f"## Evaluation Result — **{verdict.upper()}**\n\n",
                f"{summary}\n\n",
                f"### ✅ Passed ({len(passed)}/{len(results)})\n",
            ]
            for r in passed:
                lines.append(f"- **#{r.get('criterion_number')}** {r.get('criterion', '')[:80]}\n")

            if failed:
                lines.append(f"\n### ❌ Failed ({len(failed)}/{len(results)})\n")
                lines.append("**Retry these before sending your response:**\n\n")
                for r in failed:
                    lines.append(
                        f"**#{r.get('criterion_number')}** {r.get('criterion', '')}\n"
                        f"  Reason: {r.get('reason', '')}\n"
                    )
                    retry_tool = r.get("retry_tool")
                    retry_args = r.get("retry_args", {})
                    if retry_tool:
                        args_str = json.dumps(retry_args, ensure_ascii=False)
                        lines.append(f"  Retry: `{retry_tool}` args: `{args_str}`\n")
                    else:
                        lines.append("  Retry: not possible — explain gap to user\n")
                    lines.append("\n")

                lines.append(
                    "**ACTION REQUIRED**: Execute the retry tool calls above, then update "
                    "your draft to address each failed criterion before sending.\n"
                )
            else:
                lines.append(
                    "\n🎉 All criteria passed. Your response is ready to send.\n"
                )

            return "".join(lines)

        except json.JSONDecodeError as exc:
            logger.warning("plan_task[evaluate]: JSON parse failed ({}), returning raw", exc)
            return f"## Evaluation (raw)\n\n{raw_content or '(empty)'}"  # type: ignore[possibly-undefined]

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("plan_task[evaluate]: failed with {}", exc)
            return (
                f"plan_task[evaluate] failed ({exc}). "
                f"Proceed carefully — manually verify all criteria before sending."
            )
