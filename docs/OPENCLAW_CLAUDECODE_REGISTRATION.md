# 一页式接入：OpenClaw / Claude Code（本地运行，仅开发调试）

> 当前生产推荐为远程托管模式：
> - [REMOTE_MCP_REGISTRATION_ONE_PAGER.md](REMOTE_MCP_REGISTRATION_ONE_PAGER.md)
> - [REMOTE_MCP_HOSTED_SPEC_V1.md](REMOTE_MCP_HOSTED_SPEC_V1.md)
>
> 本文档仅保留给开发联调场景。

## 0. 前提说明

- 本方案是**本地运行模式**：MCP Server 跑在用户本机。
- AK/SK 仅在用户本机环境变量中使用，不通过 Tool 参数传递。
- 启动命令入口：`python3 main.py mcp`（见 `main.py` 和 `src/mofang_mcp/cli.py`）。

---

## 1. 安装与准备

```bash
# 1) 获取代码
cd /your/workspace
git clone <your-repo-url> mofang-skill-v2
cd mofang-skill-v2

# 2) 安装依赖（按项目实际方式二选一）
# pip install -r requirements.txt
# 或 uv sync / poetry install
```

---

## 2. 配置环境变量（用户自己的账号）

```bash
export BASE_URL="https://openapi.qike366.com"
export APP_ACCESS_KEY="your_ak"
export APP_SECRET_KEY="your_sk"
```

建议：把上述变量写入用户自己的 shell profile（如 `~/.zshrc`），避免每次手工导出。

---

## 3. 本地自测（先验证再接入）

```bash
# 查看工具清单
python3 main.py list-tools

# 调用单个工具（示例）
python3 main.py call route_query '{"query":"查一下华为最近一年招投标和裁判文书"}'
```

预期：能返回 `code=0` 且有业务数据。

---

## 4. 注册到 Claude Code / OpenClaw（本地模式）

将以下配置加入 MCP 配置文件（按你的客户端位置填写）：

```json
{
  "mcpServers": {
    "mofang-enterprise-query": {
      "command": "python3",
      "args": [
        "/绝对路径/mofang-skill-v2/main.py",
        "mcp"
      ],
      "env": {
        "BASE_URL": "https://openapi.qike366.com",
        "APP_ACCESS_KEY": "your_ak",
        "APP_SECRET_KEY": "your_sk"
      }
    }
  }
}
```

> 注意：`args` 里请使用 `main.py` 的**绝对路径**。

---

## 5. 可用工具（A0）

- `route_query`
- `resolve_entity`
- `company_snapshot`
- `company_profile`
- `company_risk`
- `company_bidding`

其中 `company_profile` / `company_risk` / `company_bidding` 是对 `company_snapshot` 的单模块封装。

---

## 6. 常见问题（FAQ）

### Q1：为什么看到了两个相似的 MCP（例如带 `-user` 和不带）？
因为同一个服务同时配置在了“项目级”和“全局级”。
建议只保留一个来源，避免重复注册。

### Q2：401 或 token 过期怎么办？
本项目由 Gateway 在进程内管理 token（AK/SK -> token + 缓存 + 自动刷新）。
如仍持续 401，请优先检查 AK/SK 是否正确、是否有权限、BASE_URL 是否正确。

### Q3：为什么工具调用不到？
按顺序检查：
1. `python3 main.py list-tools` 是否正常
2. 环境变量是否已生效
3. MCP 配置中 `main.py` 路径是否为绝对路径
4. 客户端是否已重载/重启会话

---

## 7. 安全建议

- 不要把真实 AK/SK 提交到仓库。
- 不要把 AK/SK 放到 Tool 入参。
- 如需调试日志，建议仅写本地临时路径，并注意脱敏。
