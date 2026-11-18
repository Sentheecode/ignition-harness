# 脱敏 MCP 采集器（只读、测试环境）

入口：[collect_mcp_evidence.py](collect_mcp_evidence.py)。仅依赖 Python 3.10+ 标准库。关联 [两版本隔离验证清单](../docs/validation/isolated-gateway-checklist-2026-11-18.md)。

本工具把 PR #1 中的[采集程序说明（固定 commit）](https://github.com/Sentheecode/ignition-harness/blob/7d653e7dcd88f3d0f61b621f6a0ee3b97e875167/docs/evidence/catalyst-mcp-collection-procedure-2026-11-17.md)变成可执行脚本；不合并该 PR，也不修改其调查结论。

## 范围

- 操作者提供**精确 MCP endpoint**，脚本不扫描、不推测路径、不尝试认证候选。
- 只发 `initialize` → `notifications/initialized` → 分页 `tools/list`。不执行工具、不发送工具参数、不登录 Designer、不重启或配置 Gateway。
- 同时接受 JSON 与 SSE 响应，忽略 SSE 心跳和非本请求响应。协商版本必须与指定版本相同，默认是 MCP 规范版本 `2025-06-18`；这不是 Ignition 版本或兼容承诺。
- 服务端分配的 MCP session ID 仅在内存中用于后续请求，不写入证据。采集会占用一个临时 MCP session，不发送 DELETE，待服务端自然过期。
- 认证只读取私有 JSON 对象里的实际头名/值，不假定任何 Ignition/Artek 头。协议管理头不能由该文件覆盖。
- 可选 OpenAPI 仅对显式输入的同 origin URL 发 GET，使用独立头文件；不继承 MCP 凭据。URL 不允许 userinfo、query、fragment；不跟随重定向，不使用环境代理，HTTPS 采用系统证书验证。

## 私有输入

在仓库外创建权限为 700 的目录。下面的环境变量由操作者填入已确认的隔离目标；不要把 key/token 放在命令行、URL 或环境变量里。

```bash
mkdir -m 700 /path/outside/repository/ignition-lab-private
```

`metadata.json` 至少包含以下字段；**只有确认新建环境隔离后才填写 true**。其他可选字段见脚本 `fields`，例如 gateway_build、edition、license_state、modules、architecture、model_provider_configured 和 primitives_selection_note。不要填真实站点名。

```json
{
  "gateway_version": "2027.2.0-beta1",
  "isolated_test_gateway": true,
  "synthetic_data_only": true,
  "modules": []
}
```

8.3.9 路径使用 `"gateway_version": "8.3.9"`。modules 应由操作者补全实际模块版本；脚本记录的是操作者声明，**不会独立验证 Gateway 身份、隔离状态或安装情况**。

`mcp-headers.json` 是操作者已从目标 Gateway 确认的认证头对象。匿名对照用 `{}`。这里故意不提供供应商头名示例；多个头一起成功也不证明每个头都是必需的。

`redactions.json` 是字符串数组，填入应删除的真实用户名、项目名、内部域名、Tag 路径、自定义工具名中的敏感片段等。可使用 `[]`，但发布前仍要人工检查。两个私有输入文件均设为 600，勿提交。

## 单次采集

`LAB_MCP_ENDPOINT` 必须是从**该测试 Gateway**复制、核验过的 endpoint，不能照抄其他 Gateway 的历史记录。`LAB_PRIVATE_DIR`、`LAB_EVIDENCE_FILE` 指向仓库外位置；输出必须是不存在的新文件，父目录必须已存在。

```bash
python research/collect_mcp_evidence.py \
  --isolated-test-gateway \
  --url "$LAB_MCP_ENDPOINT" \
  --metadata-file "$LAB_PRIVATE_DIR/metadata.json" \
  --headers-file "$LAB_PRIVATE_DIR/mcp-headers.json" \
  --redactions-file "$LAB_PRIVATE_DIR/redactions.json" \
  --output "$LAB_EVIDENCE_FILE"
```

带 OpenAPI 时，在同一命令后追加：

```bash
  --openapi-url "$LAB_OPENAPI_URL" \
  --openapi-headers-file "$LAB_PRIVATE_DIR/openapi-headers.json"
```

`LAB_OPENAPI_URL` 来自该 Gateway 的已确认 API 文档。`/openapi.json` 是待采集目标，但脚本不会补全它或替你决定 REST 认证。无 openapi-headers-file 时 OpenAPI 请求是匿名请求，不沿用 MCP 头。

候选认证应**分别运行**：先匿名，再以独立私有头文件运行每个已有出处的候选；输出各用新文件。不要自动暴力尝试、改变权限或把 MCP Server 设为 Public 来换取成功。401/403 只说明该次组合失败，不能证明其他凭据形式不存在。

可选 `--max-pages`（默认 100，上限 1000）和每次网络操作 `--timeout`（默认 15 秒，上限 60 秒）。单个响应上限 8 MiB。不会自动重试、重新初始化或调用任何工具；会话失效另行采集，避免把两个时间点的清单拼成一个快照。

## 输出与判定

输出文件权限 600，不覆盖现有文件；stdout 只有完成状态、页数与工具数。返回码：0 为本次所请求采集完成，1 为运行失败或部分完成，2 为输入/输出等启动条件拒绝。

- `authentication.supplied_header_names`：本次实际发送的用户输入头名，不保存值。`initialize_accepted` 仅表示初始化被接受，不证明必须使用这些头。
- `http`：阶段、状态码、受限内容类型、是否出现 session/auth challenge；不保存任意响应头、重定向位置或错误体。
- `mcp.initialize`：脱敏后的实际协商结果；`mcp.tools` 保留服务器返回的完整工具对象（包括 schemas 和 annotations），不从文档补写工具。
- `mcp.pages`：每页工具数与是否有 nextCursor；原始游标只在内存中。单页且没有 nextCursor 只是“本次无后续页”，不能称为实际验证了服务器多页行为。
- `mcp.complete`：仅在页链走到没有 nextCursor 时为 true。空字符串 cursor 仍会继续；重复游标、错误响应、页数上限或后续页失败均标为不完整。
- 可选 `openapi.complete` 与 `mcp.complete` 分开。如果 MCP 完成而 OpenAPI 403，顶层 completed=false，但不会抹掉已完成的 MCP 结果。
- endpoint 的真实地址不保存。工具来源分组不能从名字猜测；另以脱敏 Configure Primitives 选择记录建立对应关系。

**脱敏不是现场信息识别器。** 脚本自动删除已知凭据、session、cursor、URL/IP、常见私密字段和 Schema default/example/examples 值，并应用操作者提供的字面量。公开文档 URL 也可能被遮蔽，因此产物是脱敏证据，不能无审查地当作原始可执行 schema。未知站点别名、任意描述文字、enum/const 等仍可能含敏感信息；人工检查是发布前的必要步骤。不要把未经检查的原始私有输入、完整 OpenAPI、截图或输出自动 git add。

## 本地测试

```bash
python -m unittest discover -v
```

测试服务只在测试进程动态分配的 loopback 端口运行，返回**明确命名为 fixture 的协议数据**，与 Ignition 无关。测试覆盖分页/SSE、实际出站认证与协议头、脱敏、失败标记、重定向拒绝和 OpenAPI 凭据隔离。通过这些测试不等于任何 Gateway 或模块已经验证通过。
