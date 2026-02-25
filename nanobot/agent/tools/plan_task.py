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
You are a task planner. Your job is to define what a COMPLETE, high-quality result
looks like for a specific user request — before any work is done.

Output ONLY valid JSON in the exact schema below. No prose, no markdown fences.

Schema:
{
  "task_type": "<short identifier e.g. travel_itinerary | product_review | restaurant_lookup>",
  "success_criteria": [
    "<specific, verifiable condition that must be true in the final output>",
    ...
  ],
  "steps": [
    {
      "id": "<short_id>",
      "action": "<tool name or action type>",
      "description": "<what to do and why>",
      "produces": "<what this step contributes to the final output>"
    },
    ...
  ],
  "quality_gate": "<single sentence: how to verify the output is complete before sending>"
}

Rules:
- success_criteria must be SPECIFIC and VERIFIABLE (not vague like "good quality")
- each criterion should be a concrete fact that can be checked (e.g. "flight prices in AUD
  from at least 2 airlines", "specific named restaurant for every meal — not generic descriptions")
- steps should be BATCHED — group all parallel tool calls into one step
  (e.g. "batch: run web_search x4 + screenshot_pages in parallel" = 1 step, 1 iteration)
- steps should be in execution order, with the right tool for each step
- quality_gate is what the agent should check before sending the final response
- keep it concise — 5-10 criteria, 4-6 steps (fewer is better — batch aggressively)
- the LAST step must always be "write_response: write the complete response satisfying all criteria"
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
