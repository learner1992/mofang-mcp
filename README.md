# mofang-skill-v2

企业查询 MCP Server A0 实现，目标是方便注册到 OpenClaw、Claude Code 等 Agent 运行时。

当前实现遵循 `docs/ENTERPRISE_QUERY_MCP_SPEC_V2.md` 的 A0 范围：

- MCP stdio server
- `tools/list`
- `tools/call`
- A0 Tools:
  - `route_query`
  - `resolve_entity`
  - `company_snapshot`
  - `company_profile`
  - `company_risk`
  - `company_bidding`
- Gateway Core 内置于 MCP Server 进程内
- Gateway 统一负责当前进程 `APP_ACCESS_KEY/APP_SECRET_KEY -> token`、token 缓存和 OpenAPI 调用

## 启动

```bash
cd /Users/xutengqiang/Desktop/claude/mofang-skill-v2
export BASE_URL="https://openapi.qike366.com"
export APP_ACCESS_KEY="your_ak"
export APP_SECRET_KEY="your_sk"
python3 main.py mcp
```

## 本地命令

```bash
python3 main.py list-tools
python3 main.py call route_query '{"query":"查一下华为最近一年招投标和裁判文书"}'
```

## 注册到 Claude Code / OpenClaw

参考 [docs/OPENCLAW_CLAUDECODE_REGISTRATION.md](docs/OPENCLAW_CLAUDECODE_REGISTRATION.md)。
