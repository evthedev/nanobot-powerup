"""MCP client: connects to MCP servers and wraps their tools as native nanobot tools."""

from contextlib import AsyncExitStack
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


class MCPToolWrapper(Tool):
    """Wraps a single MCP server tool as a nanobot Tool."""

    def __init__(self, session, server_name: str, tool_def):
        self._session = session
        self._original_name = tool_def.name
        self._name = f"mcp_{server_name}_{tool_def.name}"
        self._description = tool_def.description or tool_def.name
        self._parameters = tool_def.inputSchema or {"type": "object", "properties": {}}

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types
        is_screenshot = "screenshot" in self._original_name.lower()
        if is_screenshot:
            logger.info("MCP {} ← calling with kwargs={}", self._original_name, {k: str(v)[:100] for k, v in kwargs.items()})
        result = await self._session.call_tool(self._original_name, arguments=kwargs)
        if is_screenshot:
            content_list = getattr(result, "content", None) or []
            logger.info(
                "MCP {} → isError={} | content_types={}",
                self._original_name,
                getattr(result, "isError", False),
                [type(b).__name__ for b in content_list],
            )
        # Large page content from navigate/wait_for/snapshot balloons LLM context fast.
        # Keep only the first 6000 chars — enough to extract prices from any page.
        _CONTENT_TRUNCATE = 6000
        is_navigate = True  # Apply truncation to ALL playwright tool text results

        parts = []
        for block in (getattr(result, "content", None) or []):
            if isinstance(block, types.TextContent):
                text = block.text
                if is_navigate and len(text) > _CONTENT_TRUNCATE:
                    logger.debug(
                        "MCP {} — truncating result {} → {} chars",
                        self._original_name, len(text), _CONTENT_TRUNCATE,
                    )
                    text = text[:_CONTENT_TRUNCATE] + "\n...[truncated — extract prices from what's visible above]"
                if is_screenshot:
                    logger.debug("MCP {} text result: {}", self._original_name, text[:200])
                parts.append(text)
            elif isinstance(block, types.ImageContent):
                # Drop base64 data — returning it bloats LLM context by 20k+ tokens per screenshot.
                # The file was already saved to disk by the MCP server; the LLM just needs to know it succeeded.
                fmt = (block.mimeType or "image/png").split("/")[-1]
                parts.append(f"[Screenshot saved as {fmt}. File is on disk. Proceed to next step.]")
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"


async def connect_mcp_servers(
    mcp_servers: dict, registry: ToolRegistry, stack: AsyncExitStack
) -> None:
    """Connect to configured MCP servers and register their tools."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    for name, cfg in mcp_servers.items():
        try:
            if cfg.command:
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif cfg.url:
                from mcp.client.streamable_http import streamable_http_client
                if cfg.headers:
                    http_client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=cfg.headers,
                            follow_redirects=True
                        )
                    )
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(cfg.url, http_client=http_client)
                    )
                else:
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(cfg.url)
                    )
            else:
                logger.warning("MCP server '{}': no command or url configured, skipping", name)
                continue

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            tools = await session.list_tools()
            for tool_def in tools.tools:
                wrapper = MCPToolWrapper(session, name, tool_def)
                registry.register(wrapper)
                logger.debug("MCP: registered tool '{}' from server '{}'", wrapper.name, name)

            logger.info("MCP server '{}': connected, {} tools registered", name, len(tools.tools))
        except Exception as e:
            logger.error("MCP server '{}': failed to connect: {}", name, e)
