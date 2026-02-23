"""Spawn tool for creating background subagents."""

from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """
    Tool to spawn a subagent for background task execution.
    
    The subagent runs asynchronously and announces its result back
    to the main agent when complete.
    """
    
    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
    
    @property
    def name(self) -> str:
        return "spawn"
    
    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done. "
            "Choose the model based on task complexity: use a capable reasoning model "
            "(e.g. anthropic/claude-sonnet-4-6) for analysis, coding, or multi-step tasks; "
            "use a fast cheap model (e.g. openai/gpt-4.1-mini) for simple summarisation, "
            "formatting, or lookup tasks. Omit model to use the default."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Model to use for this subagent. Use provider/model format "
                        "(e.g. 'anthropic/claude-sonnet-4-6', 'openai/gpt-4.1-mini', "
                        "'openai/gpt-4.1-nano'). Omit to use the default model. "
                        "Pick a cheaper/faster model for simple tasks (summarise, reformat, lookup); "
                        "pick a stronger model for reasoning, coding, or multi-step tasks."
                    ),
                },
            },
            "required": ["task"],
        }
    
    async def execute(self, task: str, label: str | None = None, model: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        return await self._manager.spawn(
            task=task,
            label=label,
            model=model,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
        )
