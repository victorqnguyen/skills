"""Connection-only handling for MCP servers.

SECURITY ARCHITECTURE: This module connects to already-running MCP servers.
It does NOT spawn processes. Process lifecycle (starting, stopping, restarting
MCP servers) belongs to OS-level process management: systemd, launchd, Docker,
pm2, supervisord, etc.

A communication protocol should not be a process launcher. Mixing "here's a
shell command" with "here's a tool description the AI reads" turns every
context injection path into an RCE vector. Separating connection from lifecycle
eliminates the entire CVE family (14+ CVEs, 200K+ vulnerable instances as of
April 2026) traced to StdioServerParameters spawning arbitrary subprocesses.

See: OX Security advisory, April 15 2026
     CVE-2026-30623, CVE-2026-22252, CVE-2026-22688, CVE-2026-30615, et al.
"""

from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class MCPConnection(ABC):
    """Base class for MCP server connections.

    All connection types connect to already-running servers.
    No connection type spawns a process.
    """

    def __init__(self):
        self.session = None
        self._stack = None

    @abstractmethod
    def _create_context(self):
        """Create the connection context based on connection type."""

    async def __aenter__(self):
        """Initialize MCP server connection."""
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        try:
            ctx = self._create_context()
            result = await self._stack.enter_async_context(ctx)

            if len(result) == 2:
                read, write = result
            elif len(result) == 3:
                read, write, _ = result
            else:
                raise ValueError(f"Unexpected context result: {result}")

            session_ctx = ClientSession(read, write)
            self.session = await self._stack.enter_async_context(session_ctx)
            await self.session.initialize()
            return self
        except BaseException:
            await self._stack.__aexit__(None, None, None)
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up MCP server connection resources."""
        if self._stack:
            await self._stack.__aexit__(exc_type, exc_val, exc_tb)
        self.session = None
        self._stack = None

    async def list_tools(self) -> list[dict[str, Any]]:
        """Retrieve available tools from the MCP server."""
        response = await self.session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the MCP server with provided arguments."""
        result = await self.session.call_tool(tool_name, arguments=arguments)
        return result.content


class MCPConnectionHTTP(MCPConnection):
    """MCP connection using Streamable HTTP.

    Connects to an already-running MCP server at the given URL.
    The server must be started independently via OS process management
    (systemd, launchd, Docker, pm2, etc).
    """

    def __init__(self, url: str, headers: dict[str, str] = None):
        super().__init__()
        self.url = url
        self.headers = headers or {}

    def _create_context(self):
        return streamablehttp_client(url=self.url, headers=self.headers)


def create_connection(
    url: str,
    headers: dict[str, str] = None,
) -> MCPConnection:
    """Create an MCP connection to an already-running server.

    Args:
        url: Server URL (e.g., http://localhost:8080/mcp,
             https://my-server.tailnet.ts.net/mcp)
        headers: Optional HTTP headers for authentication

    Returns:
        MCPConnection instance

    Example:
        # Server started independently (systemd, launchd, Docker, etc.)
        # MCP config contains ONLY connection targets, never shell commands.
        async with create_connection("http://localhost:8080/mcp") as conn:
            tools = await conn.list_tools()
            result = await conn.call_tool("search", {"query": "test"})
    """
    if not url:
        raise ValueError("URL is required. MCP servers must be running independently.")
    return MCPConnectionHTTP(url=url, headers=headers)
