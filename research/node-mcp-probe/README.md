# MCP 客户端兼容性探测

研究工具，不是 Harness 产品。使用已检查 DSH commit 所固定的 `@modelcontextprotocol/client@2.2.0`。

```bash
npm ci --prefix research/node-mcp-probe
node research/node-mcp-probe/probe.cjs \
  --url 'http://127.0.0.1:18088/data/catalyst-agent/mcp-servers/HarnessLab' \
  --headers-file /private/api-headers.json \
  --output /private/probe-result.json \
  --tag '[default]HarnessLab/Temperature'
```

默认只执行连接与工具发现。提供 `--tag` 时会调用目标 Ignition Server 的 `realtime` 读取工具。凭据文件放在仓库外；输出不记录认证头和 MCP session ID。结果反映目标 Gateway 的实际工具和权限，不保证跨 build 一致。
