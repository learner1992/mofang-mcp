# mofang-skill-v2

企业查询 MCP Server A0 实现，当前分支以本地 `stdio` 运行模式为主，方便注册到 OpenClaw、Claude Code 等 Agent 运行时。

当前实现遵循 `docs/ENTERPRISE_QUERY_MCP_SPEC_V2.md` 的 A0 范围：

- MCP Tool Layer
- `tools/list`
- `tools/call`
- A0 Tools:
  - `route_query`
  - `resolve_entity`
  - `company_snapshot`
  - `company_profile`
  - `company_risk`
  - `company_bidding`
  - `bidding_search`
- Gateway Core 负责 `AK/SK -> token`、token 缓存和 OpenAPI 调用

## 本地开发调试模式（stdio）

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
python3 main.py call bidding_search '{"query":"小米","search_type":"1","options":{"current":1,"limit":10}}'
```

## 注册到 Claude Code / OpenClaw

本地 stdio 接入参考：

- [docs/OPENCLAW_CLAUDECODE_REGISTRATION.md](docs/OPENCLAW_CLAUDECODE_REGISTRATION.md)
