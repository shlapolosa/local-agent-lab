"""The two agents of the Visio->ArchiMate workflow, as Microsoft Agent Framework ChatAgents
pointed at the lab gateway. Each agent authenticates with its own credential; spend attributes
per agent key.

Client & state (see [[agent-framework-tool-calling]] / CLAUDE.md): we use the modern OpenAI
**Responses API** (`OpenAIChatClient`), but forced STATELESS via `store=False`. Reason: the
gateway's Ollama Cloud upstream implements only the non-stateful flavor of `/v1/responses`
(`store`/`previous_response_id`/`conversation` are inert — verified), so AF's default stateful
turn (previous_response_id + delta) yields an empty post-tool message. `store=False` makes AF
resend full context each turn (stateless replay), which works. The toggle is `AGENT_RESPONSES_STORE`
in `.env` (false for our Ollama-backed gateway; set true only against a Responses-stateful backend
like Azure OpenAI / Foundry). We can't derive the upstream from the client (AF sees only the
gateway URL), hence the explicit env switch — consistent with the lab's one-.env-toggle style.

Instructions are composed from the greenfield prompts + method + the registered visio-reader skill.
"""
import os
from pathlib import Path

from agent_framework import Agent, ChatOptions
from agent_framework.openai import OpenAIChatClient

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1] / ".claude" / "skills"
MODEL = os.environ.get("VISIO_AGENT_MODEL", "kimi-k3")
# store=True only when the gateway's upstream actually persists Responses state (Azure/Foundry/OpenAI).
STORE = os.environ.get("AGENT_RESPONSES_STORE", "false").strip().lower() in ("1", "true", "yes")


def _read(rel: str) -> str:
    return (HERE / rel).read_text()


def _strip_frontmatter(md: str) -> str:
    if md.lstrip().startswith("---"):
        return md.split("---", 2)[2].strip()
    return md


def ba_instructions() -> str:
    skill = _strip_frontmatter((SKILLS / "visio-reader" / "SKILL.md").read_text())
    return "\n\n".join([
        _read("prompts/ba.md"),
        "## Conversion method\n\n" + _read("references/method.md"),
        "## Visio-reading skill\n\n" + skill,
    ])


def architect_instructions() -> str:
    return "\n\n".join([
        _read("prompts/architect.md"),
        "## Conversion method\n\n" + _read("references/method.md"),
    ])


def read_vsdx_tool():
    """LOCAL-DEV ONLY: a function tool the BA calls to read a Visio file from a filesystem path
    (no egress). Refs are never read here — for art:// inputs the BA gets the gateway's
    storage_mcp tools instead (ba_tools), so a workload holds no store credentials."""
    from . import inputs as I

    def read_vsdx(source: str) -> dict:
        """Read a Microsoft Visio .vsdx diagram into {pages, shapes, connectors}. `source` is the
        exact path you were given. Call this BEFORE describing the system."""
        return I.read_vsdx(source)

    return read_vsdx


def read_document_tool():
    """LOCAL-DEV ONLY: a function tool the BA calls to read a requirements document from a path —
    parsed locally, returned as plain text; that text then reaches the model through the gateway,
    where the PII guardrail applies like any other prompt content."""
    from . import inputs as I

    def read_document(source: str) -> str:
        """Read a requirements document (.docx, .pdf, .md, .txt, .csv) into plain text. `source` is
        the exact path you were given. Read EVERY requirements document you were given BEFORE
        producing the system description, and use it to name behaviours, data, rules and actors
        the diagram only implies."""
        return I.read_document(source)

    return read_document


# exact governed READ tools the BA may call on the upload store (gateway prefixes the server name)
BA_MCP_TOOLS = ["storage_mcp-storage_read_document", "storage_mcp-storage_read_vsdx"]


def ba_tools(headers: dict):
    """The BA's in-agent tools for art:// inputs = the gateway MCP filtered to the two read tools,
    called with the BA's own identity (its team holds the storage_mcp grant). Async-context tool —
    open it (`async with`) around the agent run. Images are NOT a BA tool: the workflow node fetches
    them (storage_get / storage_extract_figures, also via the gateway) and attaches them inline."""
    from agent_framework import MCPStreamableHTTPTool
    url = os.environ["GATEWAY_URL"].rstrip("/") + "/mcp/"
    return MCPStreamableHTTPTool(
        name="storage", url=url, allowed_tools=BA_MCP_TOOLS,
        header_provider=lambda _ctx: dict(headers), approval_mode="never_require")


# exact governed tools the Architect may call (gateway prefixes server name); NOT adoit_request_import
ARCHITECT_MCP_TOOLS = ["semantic_mcp-semantic_validate_model", "adoit_mcp-archimate_render"]


def architect_tools(headers: dict):
    """The Architect's in-agent tools = the gateway MCP, filtered to validate + render, called with
    the Architect's own identity (its key holds the grants). Returned as an async-context MCP tool;
    open it (`async with`) around the agent run. The human-gated import staging stays deterministic
    and is deliberately excluded from allowed_tools."""
    from agent_framework import MCPStreamableHTTPTool
    url = os.environ["GATEWAY_URL"].rstrip("/") + "/mcp/"
    return MCPStreamableHTTPTool(
        name="ea-tools", url=url, allowed_tools=ARCHITECT_MCP_TOOLS,
        header_provider=lambda _ctx: dict(headers), approval_mode="never_require")


def make_agent(name: str, instructions: str, credential: str,
               traceparent: dict | None = None, tools=None) -> Agent:
    """One ChatAgent -> gateway /v1 (Responses API, stateless) with the agent's own credential.
    `traceparent` (W3C headers) rides as default_headers so gateway LLM spans join the run's trace.
    `tools` optionally attaches in-agent function/MCP tools (agentic mode)."""
    # A real per-request timeout + bounded output: without them a stalled turn hangs the host
    # forever (observed: a BA run sat 2.5 h on one in-flight /v1/responses call), and kimi-k3's
    # reasoning can emit ~8k tokens per turn, which store=False then resends every turn.
    # The output cap must LEAVE ROOM for that reasoning: it counts toward max_output_tokens, and a
    # 6000 cap ended a multimodal+tools BA turn with finish=incomplete and NO final text (twice,
    # verified in gateway spans) -> the JSON gate rejected an empty description. kimi-k3 ignores
    # reasoning_effort via Ollama (verified), so 16000 is the working default; the timeout, not the
    # cap, is what protects against a hang.
    from openai import AsyncOpenAI
    http = AsyncOpenAI(
        api_key=credential, base_url=os.environ["GATEWAY_URL"].rstrip("/") + "/v1/",
        default_headers=dict(traceparent or {}),
        timeout=float(os.environ.get("AGENT_REQUEST_TIMEOUT", "300")), max_retries=1)
    client = OpenAIChatClient(model=MODEL, api_key=credential, async_client=http)
    return Agent(client=client, name=name, instructions=instructions, tools=tools,
                 default_options=ChatOptions(
                     store=STORE, max_tokens=int(os.environ.get("AGENT_MAX_OUTPUT_TOKENS", "16000"))))
