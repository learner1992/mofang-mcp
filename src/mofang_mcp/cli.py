from __future__ import annotations

import argparse
import json

from .config import Settings
from .gateway import GatewayCore
from .mcp_stdio import serve_stdio
from .tool_catalog import TOOLS


def main() -> None:
    parser = argparse.ArgumentParser(description="Mofang enterprise query MCP server")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("mcp", help="run MCP stdio server")
    sub.add_parser("list-tools", help="print tool catalog")

    call_cmd = sub.add_parser("call", help="call a tool locally")
    call_cmd.add_argument("tool")
    call_cmd.add_argument("arguments_json")

    args = parser.parse_args()
    if args.command == "mcp":
        serve_stdio()
        return
    if args.command == "list-tools":
        print(json.dumps({"tools": TOOLS}, ensure_ascii=False, indent=2))
        return
    if args.command == "call":
        gateway = GatewayCore(Settings.from_env())
        arguments = json.loads(args.arguments_json)
        from .mcp_stdio import McpServer

        server = McpServer(gateway)
        result = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": args.tool,
                    "arguments": arguments,
                },
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

