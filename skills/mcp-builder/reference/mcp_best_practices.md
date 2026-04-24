# MCP Server Best Practices

## Quick Reference

### Server Naming
- **Python**: `{service}_mcp` (e.g., `slack_mcp`)
- **Node/TypeScript**: `{service}-mcp-server` (e.g., `slack-mcp-server`)

### Tool Naming
- Use snake_case with service prefix
- Format: `{service}_{action}_{resource}`
- Example: `slack_send_message`, `github_create_issue`

### Response Formats
- Support both JSON and Markdown formats
- JSON for programmatic processing
- Markdown for human readability

### Pagination
- Always respect `limit` parameter
- Return `has_more`, `next_offset`, `total_count`
- Default to 20-50 items

### Transport
- **Streamable HTTP**: For all servers — local and remote
- Avoid SSE (deprecated in favor of streamable HTTP)
- **STDIO transport is not recommended** due to process-spawning security risks.
  See "Transport: Connection-Only Architecture" below.

---

## Server Naming Conventions

Follow these standardized naming patterns:

**Python**: Use format `{service}_mcp` (lowercase with underscores)
- Examples: `slack_mcp`, `github_mcp`, `jira_mcp`

**Node/TypeScript**: Use format `{service}-mcp-server` (lowercase with hyphens)
- Examples: `slack-mcp-server`, `github-mcp-server`, `jira-mcp-server`

The name should be general, descriptive of the service being integrated, easy to infer from the task description, and without version numbers.

---

## Tool Naming and Design

### Tool Naming

1. **Use snake_case**: `search_users`, `create_project`, `get_channel_info`
2. **Include service prefix**: Anticipate that your MCP server may be used alongside other MCP servers
   - Use `slack_send_message` instead of just `send_message`
   - Use `github_create_issue` instead of just `create_issue`
3. **Be action-oriented**: Start with verbs (get, list, search, create, etc.)
4. **Be specific**: Avoid generic names that could conflict with other servers

### Tool Design

- Tool descriptions must narrowly and unambiguously describe functionality
- Descriptions must precisely match actual functionality
- Provide tool annotations (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
- Keep tool operations focused and atomic

---

## Response Formats

All tools that return data should support multiple formats:

### JSON Format (`response_format="json"`)
- Machine-readable structured data
- Include all available fields and metadata
- Consistent field names and types
- Use for programmatic processing

### Markdown Format (`response_format="markdown"`, typically default)
- Human-readable formatted text
- Use headers, lists, and formatting for clarity
- Convert timestamps to human-readable format
- Show display names with IDs in parentheses
- Omit verbose metadata

---

## Pagination

For tools that list resources:

- **Always respect the `limit` parameter**
- **Implement pagination**: Use `offset` or cursor-based pagination
- **Return pagination metadata**: Include `has_more`, `next_offset`/`next_cursor`, `total_count`
- **Never load all results into memory**: Especially important for large datasets
- **Default to reasonable limits**: 20-50 items is typical

Example pagination response:
```json
{
  "total": 150,
  "count": 20,
  "offset": 0,
  "items": [...],
  "has_more": true,
  "next_offset": 20
}
```

---

## Transport: Connection-Only Architecture

### Principle: Separate Discovery, Installation, Lifecycle, and Connection

MCP should own the connection layer and nothing else. A communication protocol
should not try to discover packages, install software, or launch processes.
Those are separate concerns with separate trust boundaries and mature tooling.

The responsibilities break down like this:

- **Discovery**: finding a server belongs to package registries and marketplaces
- **Installation**: getting server software onto a machine belongs to package managers
- **Lifecycle**: starting, stopping, and restarting a server belongs to service managers
- **Connection**: talking to an already-running server is MCP's job

In practical terms, MCP configs should contain **connection targets** (URLs),
never **shell commands**. Registries such as npm, PyPI, Docker Hub, or signed
marketplaces solve discovery. Package managers such as `npm`, `brew`, `apt`,
or Docker solve installation. Service managers such as `systemd`, `launchd`,
Docker, or `pm2` solve lifecycle with established permission models, sandboxing,
logging, restart policies, and health checks.

**Why this matters**: The April 2026 CVE family stemmed from collapsing these
layers into a single MCP config surface. The STDIO transport's
`StdioServerParameters` takes a `command` field and passes it directly to
`subprocess.Popen()` / `child_process.spawn()` with no sanitization. That
architectural conflation produced 14+ CVEs, 200K+ vulnerable instances, and
9/11 MCP marketplace registries successfully poisoned (OX Security, April 2026).
The attack surface drops sharply when MCP stops spawning processes and returns to
its proper role as a connection protocol.

### Streamable HTTP (Use This)

**Best for**: All servers — local and remote

**Characteristics**:
- Connects to an already-running server at a URL
- Bidirectional communication over HTTP
- Supports multiple simultaneous clients
- Can be deployed locally or as a cloud service
- Enables server-to-client notifications
- **Does not spawn processes — connection only**

**Use for**:
- Local development servers (http://localhost:8080/mcp)
- Private network servers (https://my-server.tailnet.ts.net/mcp)
- Cloud-deployed services
- Multi-client scenarios

### STDIO: Do Not Use for New Servers

**STDIO as a communication pipe** (two processes talking via stdin/stdout) is
legitimate IPC. The problem is specifically `StdioServerParameters` acting as
a process launcher — taking a `command` field from config and executing it.

**If you need local IPC**: Run your server independently (launchd, systemd, Docker,
pm2) and connect via Streamable HTTP on localhost. This keeps discovery,
installation, lifecycle, and connection in their proper layers and gives you:
- The same performance characteristics
- OS-level process permissions and sandboxing for free
- No shell command in your MCP config
- No attack surface from config injection

### Process Lifecycle Management

MCP servers should be managed by existing OS tools:

| Platform | Tool | Example |
|----------|------|---------|
| **macOS** | launchd | `~/Library/LaunchAgents/com.myserver.mcp.plist` |
| **Linux** | systemd | `/etc/systemd/user/myserver-mcp.service` |
| **Container** | Docker | `docker run -d -p 8080:8080 myserver-mcp` |
| **Cross-platform** | pm2 | `pm2 start server.js --name myserver-mcp` |

These tools provide process lifecycle management — auto-restart, logging,
resource limits, permissions, startup ordering, and health checks — that
MCP configs should not duplicate.

### Discovery and Installation

MCP documentation should not teach a protocol config to double as a package
locator or installer. Discovery should happen through registries or marketplaces
with their own trust and audit mechanisms. Installation should happen through
package managers with established verification and update workflows.

That separation matters operationally as well as conceptually:

- Registries and marketplaces are where users evaluate provenance and authenticity
- Package managers are where users control installation policy and system impact
- Service managers are where users control runtime permissions and supervision
- MCP is where clients connect once a server is already running

### MCP Config: Before and After

**Before (vulnerable):**
```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": ["-y", "@my/mcp-server"],
      "env": { "API_KEY": "..." }
    }
  }
}
```

**After (connection-only):**
```json
{
  "mcpServers": {
    "my-server": {
      "type": "http",
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

The protocol becomes a protocol. The config becomes a connection string.
Discovery stays with registries. Installation stays with package managers.
Lifecycle stays with service managers. MCP stays focused on connection.
That separation reduces both attack surface and implementation complexity.

---

## Security Best Practices

### Authentication and Authorization

**OAuth 2.1**:
- Use secure OAuth 2.1 with certificates from recognized authorities
- Validate access tokens before processing requests
- Only accept tokens specifically intended for your server

**API Keys**:
- Store API keys in environment variables, never in code
- Validate keys on server startup
- Provide clear error messages when authentication fails

### Input Validation

- Sanitize file paths to prevent directory traversal
- Validate URLs and external identifiers
- Check parameter sizes and ranges
- Prevent command injection in system calls
- Use schema validation (Pydantic/Zod) for all inputs

### Error Handling

- Don't expose internal errors to clients
- Log security-relevant errors server-side
- Provide helpful but not revealing error messages
- Clean up resources after errors

### DNS Rebinding Protection

For streamable HTTP servers running locally:
- Enable DNS rebinding protection
- Validate the `Origin` header on all incoming connections
- Bind to `127.0.0.1` rather than `0.0.0.0`

---

## Tool Annotations

Provide annotations to help clients understand tool behavior:

| Annotation | Type | Default | Description |
|-----------|------|---------|-------------|
| `readOnlyHint` | boolean | false | Tool does not modify its environment |
| `destructiveHint` | boolean | true | Tool may perform destructive updates |
| `idempotentHint` | boolean | false | Repeated calls with same args have no additional effect |
| `openWorldHint` | boolean | true | Tool interacts with external entities |

**Important**: Annotations are hints, not security guarantees. Clients should not make security-critical decisions based solely on annotations.

---

## Error Handling

- Use standard JSON-RPC error codes
- Report tool errors within result objects (not protocol-level errors)
- Provide helpful, specific error messages with suggested next steps
- Don't expose internal implementation details
- Clean up resources properly on errors

Example error handling:
```typescript
try {
  const result = performOperation();
  return { content: [{ type: "text", text: result }] };
} catch (error) {
  return {
    isError: true,
    content: [{
      type: "text",
      text: `Error: ${error.message}. Try using filter='active_only' to reduce results.`
    }]
  };
}
```

---

## Testing Requirements

Comprehensive testing should cover:

- **Functional testing**: Verify correct execution with valid/invalid inputs
- **Integration testing**: Test interaction with external systems
- **Security testing**: Validate auth, input sanitization, rate limiting
- **Performance testing**: Check behavior under load, timeouts
- **Error handling**: Ensure proper error reporting and cleanup

---

## Documentation Requirements

- Provide clear documentation of all tools and capabilities
- Include working examples (at least 3 per major feature)
- Document security considerations
- Specify required permissions and access levels
- Document rate limits and performance characteristics
