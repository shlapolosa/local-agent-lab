"""End-to-end agent run: this client is what any lab agent does — one gateway
endpoint (LiteLLM /mcp), gateway key auth, no tool credentials held locally.

  agent -> LiteLLM MCP gateway (:4000/mcp) -> adoit-mcp (:9100) -> archimate engine / ADOIT

Usage:  .venv/bin/python architecture/run_via_gateway.py
"""
import asyncio
import json
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

HERE = os.path.dirname(os.path.abspath(__file__))
GATEWAY = "http://127.0.0.1:4000/mcp/"


async def main():
    key = os.environ["EA_AGENT_KEY"]   # agent identity, never the master key
    spec = json.load(open(os.path.join(HERE, "lab_model.json")))
    transport = StreamableHttpTransport(GATEWAY, headers={"Authorization": f"Bearer {key}"})
    async with Client(transport) as c:
        tools = await c.list_tools()
        names = [t.name for t in tools]
        print("tools via gateway:", names)

        def pick(suffix):
            m = [n for n in names if n.endswith(suffix)]
            if not m:
                sys.exit(f"tool {suffix} not exposed by gateway")
            return m[0]

        repos = await c.call_tool(pick("adoit_repos"), {})
        print("ADOIT repos (read via governed facade):", json.dumps(repos.data)[:160])

        val = await c.call_tool(pick("archimate_validate"), {"spec": spec})
        print(f"validate: {val.data['elements']} elements, {val.data['relations']} relations, "
              f"{len(val.data['warnings'])} warnings")
        for w in val.data["warnings"]:
            print("  WARN:", w)

        res = await c.call_tool(pick("archimate_render"), {
            "spec": spec, "outdir": os.path.join(HERE, "out"), "basename": "lab-architecture"})
        print("violations:", res.data["violations"])
        print("warnings:", len(res.data["warnings"]))
        for vid, canvas in res.data["views"].items():
            print(f"  view {vid}: {canvas[0]}x{canvas[1]}")
        print("files:")
        for f in res.data["files"]:
            print("  ", f)


if __name__ == "__main__":
    asyncio.run(main())
