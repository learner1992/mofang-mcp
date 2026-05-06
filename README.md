# mofang-skill-v2

企业查询 MCP Server A0 实现，目标是方便注册到 OpenClaw、Claude Code 等 Agent 运行时。

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
- Gateway Core 负责 `AK/SK -> token`、token 缓存和 OpenAPI 调用

## 推荐接入方式（远程托管）

生产推荐使用远程托管 MCP：客户端只需配置 `url + headers(AK/SK)`，无需 clone 代码和本地启动进程。

服务端 remote endpoint：

- `POST /mcp/company/stream`
- `Content-Type: application/json`
- 请求级 Header：`X-App-Access-Key`、`X-App-Secret-Key`

远程启动命令：

```bash
python3 main.py mcp-http --config ./config/server.yaml
```

配置文件示例（推荐 K8s 挂载）：

```yaml
base_url: https://openapi.qike366.com
manifest_path: data/api_manifest.json
cache_dir: /tmp/mofang-skill-v2-cache
timeout_seconds: 30
http_host: 0.0.0.0
http_port: 8000
http_path: /mcp/company/stream
```

兼容环境变量（无 `--config` 时生效）：

```bash
export MOFANG_MCP_HTTP_HOST="0.0.0.0"
export MOFANG_MCP_HTTP_PORT="8000"
export MOFANG_MCP_HTTP_PATH="/mcp/company/stream"
```

参考：

- [docs/REMOTE_MCP_HOSTED_SPEC_V1.md](docs/REMOTE_MCP_HOSTED_SPEC_V1.md)
- [docs/REMOTE_MCP_REGISTRATION_ONE_PAGER.md](docs/REMOTE_MCP_REGISTRATION_ONE_PAGER.md)

## 本地开发调试模式（stdio）

仅用于本地联调与回归测试（remote 实现回归）。

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

远程托管接入参考：

- [docs/REMOTE_MCP_REGISTRATION_ONE_PAGER.md](docs/REMOTE_MCP_REGISTRATION_ONE_PAGER.md)

本地 stdio 接入（仅开发调试）参考：

- [docs/OPENCLAW_CLAUDECODE_REGISTRATION.md](docs/OPENCLAW_CLAUDECODE_REGISTRATION.md)

