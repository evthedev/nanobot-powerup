"""Subagent manager for background task execution."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.reddit import RedditSearchTool
from nanobot.agent.tools.trustpilot import TrustpilotSearchTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.yelp import YelpSearchTool
from nanobot.agent.tools.message import MessageTool


class SubagentManager:
    """
    Manages background subagent execution.
    
    Subagents are lightweight agent instances that run in the background
    to handle specific tasks. They share the same LLM provider but have
    isolated context and a focused system prompt.
    """
    
    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        brave_api_key: str | None = None,
        tavily_api_key: str | None = None,
        yelp_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.brave_api_key = brave_api_key
        self.tavily_api_key = tavily_api_key
        self.yelp_api_key = yelp_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._mcp_tools: list = []  # MCP tools passed down from main agent (e.g. Playwright)

    def set_mcp_tools(self, tools: list) -> None:
        """Receive MCP tool objects from the main agent for subagent use."""
        self._mcp_tools = tools
        logger.info("SubagentManager: received {} MCP tools for subagents", len(tools))

    async def run_sync(
        self,
        label: str,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> str:
        """
        Run a single synchronous LLM call that appears in the subagent log.

        Unlike spawn() (fire-and-forget), this awaits the result and returns it
        to the caller. Used by plan_task so its LLM calls appear in the subagent
        panel instead of disappearing into the tool layer.
        """
        task_id = str(uuid.uuid4())[:8]
        logger.info("Subagent [{}] starting task: {}", task_id, label)
        try:
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=None,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if response.usage:
                u = response.usage
                logger.info(
                    "LLM usage | model={} tokens_in={} tokens_out={} total={}",
                    model,
                    u.get("prompt_tokens", 0),
                    u.get("completion_tokens", 0),
                    u.get("total_tokens", 0),
                )
            logger.info("Subagent [{}] completed successfully", task_id)
            return response.content or ""
        except Exception as exc:
            logger.error("Subagent [{}] failed: {}", task_id, exc)
            raise

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        model: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
    ) -> str:
        """
        Spawn a subagent to execute a task in the background.
        
        Args:
            task: The task description for the subagent.
            label: Optional human-readable label for the task.
            model: Optional model override (e.g. 'anthropic/claude-sonnet-4-6').
                   Defaults to the SubagentManager's configured model.
            origin_channel: The channel to announce results to.
            origin_chat_id: The chat ID to announce results to.
        
        Returns:
            Status message indicating the subagent was started.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        effective_model = model or self.model
        
        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }
        
        # Create background task
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, effective_model)
        )
        self._running_tasks[task_id] = bg_task
        
        # Cleanup when done
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))
        
        model_note = f" using {effective_model}" if model else ""
        logger.info("Spawned subagent [{}]{}: {}", task_id, model_note, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}{model_note}). I'll notify you when it completes."
    
    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        model: str,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)
        
        try:
            # Build subagent tools (no spawn tool — no recursive spawning)
            tools = ToolRegistry()
            allowed_dir = self.workspace if self.restrict_to_workspace else None
            tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            ))
            tools.register(WebSearchTool(api_key=self.brave_api_key, tavily_api_key=self.tavily_api_key))
            tools.register(WebFetchTool())
            tools.register(RedditSearchTool())
            tools.register(TrustpilotSearchTool())
            tools.register(YelpSearchTool(api_key=self.yelp_api_key))
            # Subagents can send messages (including images/media) directly back to the user
            msg_tool = MessageTool(send_callback=self.bus.publish_outbound)
            msg_tool.set_context(origin["channel"], origin["chat_id"])
            tools.register(msg_tool)
            # Add MCP tools (e.g. Playwright) passed from the main agent
            for mcp_tool in self._mcp_tools:
                tools.register(mcp_tool)
            
            # Build messages with subagent-specific prompt
            system_prompt = self._build_subagent_prompt(task)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]
            
            # Run agent loop (limited iterations)
            max_iterations = 50
            iteration = 0
            final_result: str | None = None
            
            messaged_directly = False  # Track if subagent sent message() to user

            while iteration < max_iterations:
                iteration += 1
                
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )

                if response.usage:
                    u = response.usage
                    logger.info(
                        "LLM usage | model={} tokens_in={} tokens_out={} total={}",
                        model,
                        u.get("prompt_tokens", 0),
                        u.get("completion_tokens", 0),
                        u.get("total_tokens", 0),
                    )

                if response.has_tool_calls:
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })
                    
                    # Execute tools
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug("Subagent [{}] executing: {} with arguments: {}", task_id, tool_call.name, args_str)
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        if tool_call.name == "message" and not result.startswith("Error:"):
                            messaged_directly = True
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    final_result = response.content
                    break
            
            if final_result is None:
                final_result = (
                    f"Task incomplete: reached the {max_iterations}-iteration limit "
                    f"without finishing. The task may require more steps than allowed. "
                    f"Consider breaking it into smaller subtasks."
                )
                logger.warning("Subagent [{}] hit iteration limit ({}) without completing", task_id, max_iterations)
                await self._announce_result(task_id, label, task, final_result, origin, "error", messaged_directly)
            else:
                logger.info("Subagent [{}] completed successfully", task_id)
                await self._announce_result(task_id, label, task, final_result, origin, "ok", messaged_directly)
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            await self._announce_result(task_id, label, task, error_msg, origin, "error", False)
    
    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
        messaged_directly: bool = False,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        if messaged_directly:
            # Subagent already sent the result to the user via message() — skip
            # publishing to the bus entirely so the main agent loop is not triggered
            # and cannot double-message or re-spawn.
            logger.info("Subagent [{}] messaged user directly — skipping announce to main agent", task_id)
            return
        else:
            announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""
        
        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )
        
        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])
    
    def _build_subagent_prompt(self, task: str) -> str:
        """Build a focused system prompt for the subagent."""
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"

        # Load system context files so the subagent knows the environment
        context_sections: list[str] = []
        for filename in ("AGENTS.md", "USER.md"):
            path = self.workspace / filename
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    context_sections.append(f"## {filename}\n{content}")
            except Exception:
                pass

        context_block = "\n\n".join(context_sections)

        return f"""# Subagent

## Current Time
{now} ({tz})

You are a subagent spawned by the main agent to complete a specific task.

{context_block}

## Rules
1. Stay focused — complete only the assigned task, nothing else
2. Your final response will be reported back to the main agent
3. Do not initiate conversations or take on side tasks
4. Be thorough — fully complete the task before stopping
5. For long-running commands (e.g. npm install), they may take several minutes — wait for them

## What You Can Do
- Read and write files in the workspace
- Execute shell commands (including long-running ones)
- Search the web and fetch web pages
- Complete the task thoroughly

## What You Cannot Do
- Spawn other subagents
- Access the main agent's conversation history

## Workspace
Your workspace is at: {self.workspace}
Skills are available at: {self.workspace}/skills/ (read SKILL.md files as needed)

## Sending Results to the User
You have a `message` tool. Use it to send your final result directly to the user.
- For screenshots and images: ALWAYS save to an absolute path first (e.g. `{self.workspace}/screenshot.png`), then call `message` with `media: ["{self.workspace}/screenshot.png"]`
- NEVER pass relative filenames to `message` — Telegram cannot find them
- The `filename` parameter in `mcp_playwright_browser_take_screenshot` must be an absolute path like `{self.workspace}/screenshot.png`

When you have completed the task, provide a clear summary of your findings or actions."""
    
    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)
