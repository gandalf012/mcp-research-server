# Model Context Protocol (MCP) — Architecture Summary

> Source: https://modelcontextprotocol.io/docs/concepts/architecture

---

## Scope

The Model Context Protocol includes the following projects:

- **MCP Specification**: Outlines implementation requirements for clients and servers.
- **MCP SDKs**: SDKs for different programming languages that implement MCP.
- **MCP Development Tools**: Tools for developing MCP servers and clients (e.g., MCP Inspector).
- **MCP Reference Server Implementations**: Reference implementations of MCP servers.

---

## Concepts of MCP

### Participants

MCP follows a **client-server architecture** where an MCP host (an AI application like Claude Code or Claude Desktop) establishes connections to one or more MCP servers. The host creates one MCP client per MCP server.

| Participant    | Role                                                                 |
|----------------|----------------------------------------------------------------------|
| **MCP Host**   | The AI application that coordinates and manages one or multiple MCP clients |
| **MCP Client** | Maintains a connection to an MCP server; obtains context for the host |
| **MCP Server** | A program that provides context to MCP clients (local or remote)     |

**Example**: Visual Studio Code acts as an MCP host. When it connects to the Sentry MCP server, it instantiates one MCP client for that connection. When it also connects to a local filesystem server, it instantiates a second MCP client.

---

### Layers

MCP consists of **two layers**:

1. **Data Layer** (inner layer): Defines the JSON-RPC based protocol for client-server communication — lifecycle management, tools, resources, prompts, and notifications.
2. **Transport Layer** (outer layer): Defines the communication mechanisms (channels, connection establishment, message framing, and authorization).

---

### Data Layer

Implements a **JSON-RPC 2.0** exchange protocol. Includes:

- **Lifecycle Management**: Connection initialization, capability negotiation, and termination.
- **Server Features**: Tools, resources, and prompts exposed by the server.
- **Client Features**: Sampling (LLM completions), elicitation (user input), and logging.
- **Utility Features**: Notifications and progress tracking.

---

### Transport Layer

Manages communication channels and authentication. Two transport mechanisms:

| Transport              | Description                                                                 |
|------------------------|-----------------------------------------------------------------------------|
| **Stdio Transport**    | Uses standard input/output streams for local inter-process communication. No network overhead. |
| **Streamable HTTP**    | Uses HTTP POST + optional Server-Sent Events (SSE). Supports remote servers and HTTP auth (Bearer tokens, API keys, OAuth). |

---

### Data Layer Protocol — Primitives

**Server-exposed primitives:**

| Primitive     | Description                                                                 |
|---------------|-----------------------------------------------------------------------------|
| **Tools**     | Executable functions AI can invoke (e.g., file ops, API calls, DB queries)  |
| **Resources** | Data sources for contextual information (e.g., file contents, DB records)   |
| **Prompts**   | Reusable interaction templates (e.g., system prompts, few-shot examples)    |

**Client-exposed primitives:**

| Primitive       | Description                                                              |
|-----------------|--------------------------------------------------------------------------|
| **Sampling**    | Servers request LLM completions from the client's AI application         |
| **Elicitation** | Servers request additional info or confirmation from the user            |
| **Logging**     | Servers send log messages to clients for debugging and monitoring        |

**Cross-cutting utility primitives:**

| Primitive             | Description                                                          |
|-----------------------|----------------------------------------------------------------------|
| **Tasks (Experimental)** | Durable execution wrappers for deferred results, status tracking, batch ops |

---

### Notifications

The protocol supports **real-time notifications** (JSON-RPC 2.0 messages without a response). For example, when a server's available tools change, it can push notifications to all connected clients.

---

## Lifecycle Example (Data Layer)

A typical MCP client-server interaction proceeds as:

1. **Initialize** — Client and server negotiate capabilities.
2. **Discover** — Client calls `tools/list`, `resources/list`, `prompts/list`.
3. **Operate** — Client invokes tools (`tools/call`), reads resources, uses prompts.
4. **Notify** — Server pushes real-time updates to the client.
