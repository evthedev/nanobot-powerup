"""plan_task tool — uses a smart LLM (claude-sonnet) to define a structured execution plan
before carrying out any complex task.

The planner asks: "what does a complete, independently usable result look like for THIS
specific request?" and returns a concrete todo list with acceptance criteria. The main
agent (or subagents) then executes against those criteria and self-validates before
responding to the user.

Architecture:
  plan_task (Sonnet, ~$0.003/call) → structured plan JSON
  execute steps (GPT-4o-mini)      → carries out grunt work
  self-validate against criteria   → prevents deferral / incomplete output
"""

import json
import re
from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

# Use Sonnet for planning — cheap per call, significantly better structured reasoning.
# Falls back to caller's model if Sonnet is unavailable.
_PLANNER_MODEL = "anthropic/claude-sonnet-4-5"

_SYSTEM_PROMPT = """\
You are a task planner. Your job is to produce a concrete, executable plan for a
specific user request — before any work is done.

The plan is returned to the main agent (GPT-4o-mini), which will execute it step by
step by calling tools. You do NOT call any tools yourself — you only plan.

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

Rules for success_criteria:
- Must be SPECIFIC and VERIFIABLE — not vague ("good quality" is banned)
- Example good criteria: "return flight prices in AUD from ≥2 airlines with actual numbers",
  "specific named restaurant for every meal — names like 'Ichiran' not 'local ramen shop'",
  "event venue confirmed with street address", "3 hotel options with per-night AUD price"
- 5–8 criteria

Rules for steps:
- BATCH aggressively — all independent tool calls go in ONE step with "batch": true
- Only create a new step when output from the previous step is REQUIRED as input
- Typical complex task = 2–3 steps: (1) batch all research in parallel, (2) write response
- Include REAL, SPECIFIC tool arguments — not placeholders
  - For web_search: write the actual query string
  - For screenshot_pages: write the actual slug, URL, label, wait_seconds
  - For reddit_search: write the actual query
- The FINAL step is always {"id":"write_response","batch":false,"tools":[],
  "why":"Write the complete response satisfying all success_criteria. Embed all screenshots."}

Available tools: web_search, web_fetch, screenshot_pages, reddit_search, trustpilot_search,
read_file, write_file, exec, spawn

For travel tasks: ALWAYS include read_file(path="memory/MEMORY.md") in step_1 alongside
other research calls — the agent may have stored trip preferences, dates, or constraints
there that override the user's request.

Tool signatures (abbreviated):
- web_search(query: str) → search results
- screenshot_pages(slug: str, pages: [{url, label, wait_seconds}]) → content + image URLs
- reddit_search(query: str, limit: int) → reddit posts
- trustpilot_search(query: str, include_reviews: bool, review_count: int) → reviews
"""


class PlanTaskTool(Tool):
    """
    Calls a smart LLM (Claude Sonnet) to define a structured execution plan for a
    complex task before any work begins. Returns a JSON plan with:
      - success_criteria: specific verifiable conditions the output must meet
      - steps: ordered execution steps with tool assignments
      - quality_gate: final self-check before responding

    Call this FIRST for any complex task (travel research, product review, research
    aggregation, etc.). Then execute each step and validate against success_criteria
    before sending your response.

    Cost: ~$0.003 per plan call. Only use for complex multi-step tasks.
    """

    def __init__(self, provider: "LLMProvider"):
        self._provider = provider

    @property
    def name(self) -> str:
        return "plan_task"

    @property
    def description(self) -> str:
        return (
            "Uses a smart LLM to define a structured execution plan for a complex task. "
            "Returns success_criteria (what the output MUST contain), ordered steps (which "
            "tools to call and why), and a quality_gate (self-check before responding). "
            "Call this FIRST for travel itineraries, product reviews, research tasks, or "
            "any multi-step request where quality matters. Then execute each step and "
            "validate against the criteria before sending your response."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": (
                        "The user's request in full. Include all relevant details: "
                        "destination, dates, budget, preferences, etc."
                    ),
                },
                "task_type": {
                    "type": "string",
                    "description": (
                        "Category of task to help the planner apply domain knowledge. "
                        "Examples: 'travel_itinerary', 'product_review', 'restaurant_lookup', "
                        "'event_research', 'comparison', 'news_summary'."
                    ),
                },
                "available_tools": {
                    "type": "string",
                    "description": (
                        "Comma-separated list of tools available for execution. "
                        "The planner will assign tools to steps accordingly. "
                        "Example: 'web_search, screenshot_pages, reddit_search, trustpilot_search'"
                    ),
                },
            },
            "required": ["goal", "task_type"],
        }

    async def execute(  # pylint: disable=arguments-differ
        self,
        goal: str,
        task_type: str,
        available_tools: str = "web_search, screenshot_pages, reddit_search, trustpilot_search, web_fetch",
        **kwargs: Any,
    ) -> str:
        logger.info("plan_task: planning '{}' using {}", task_type, _PLANNER_MODEL)

        prompt = (
            f"Task type: {task_type}\n\n"
            f"User request:\n{goal}\n\n"
            f"Available tools: {available_tools}\n\n"
            f"Define the execution plan."
        )

        try:
            response = await self._provider.chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                model=_PLANNER_MODEL,
                max_tokens=1024,
                temperature=0.2,
            )

            raw = (response.content or "").strip()
            # Strip any accidental markdown fences the model might add
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            plan = json.loads(raw)
            logger.info(
                "plan_task: got plan — {} criteria, {} steps",
                len(plan.get("success_criteria", [])),
                len(plan.get("steps", [])),
            )

            # Return a human-readable version the main agent can directly act on
            criteria = plan.get("success_criteria", [])
            steps = plan.get("steps", [])
            quality_gate = plan.get("quality_gate", "")

            lines = [
                f"## Execution Plan — {plan.get('task_type', task_type)}\n\n",
                "### ✅ Success Criteria\n",
                "Your response MUST satisfy ALL of these before sending:\n\n",
            ]
            for i, c in enumerate(criteria, 1):
                lines.append(f"{i}. {c}\n")

            lines.append("\n### 📋 Steps\n\n")
            for s in steps:
                lines.append(
                    f"**{s.get('id', '?')}** — {s.get('action', '')} — "
                    f"{s.get('description', '')} → _{s.get('produces', '')}_\n\n"
                )

            lines.append(f"### 🔍 Quality Gate\n{quality_gate}\n\n")
            lines.append(
                "Execute the steps above. Before sending your response, verify EVERY "
                "criterion is satisfied. If any criterion cannot be met (e.g. data unavailable), "
                "explain why — do NOT leave it blank or use placeholders.\n"
            )

            return "".join(lines)

        except json.JSONDecodeError as exc:
            logger.warning("plan_task: JSON parse failed ({}), returning raw", exc)
            return f"## Execution Plan\n\n{response.content or '(empty)'}"

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("plan_task: failed with {}", exc)
            return (
                f"plan_task failed ({exc}). Proceed without a formal plan — "
                f"but ensure your response is complete and verifiable before sending."
            )
