# 运行时采集 Catalyst / Artek MCP 工具清单的程序

日期：2026-11-17（Asia/Singapore）。本文件是**待在实机 Gateway 上执行的程序**，不是已完成的 `tools/list` 结果。不要把这里的候选请求头写成已验证行为。

完整工具清单无法仅凭公开手册、Configure Primitives 截图或 SDK Javadoc 得到。截图里的显示名也不保证等于协商后的 wire 名。

## 0. 前置条件（由用户提供隔离环境）

- 开发/测试 Gateway，不要用生产系统。2027 Beta 官方要求只用于开发或测试系统。
- 路径 A：`inductiveautomation/ignition:8.3.9` + 固定版本 Artek-MCP（供应商最低版本是 8.3.4，产品基线仍是 8.3.9）。
- 路径 B：`inductiveautomation/ignition:2027.2.0-beta1` + Catalyst Core 与 Catalyst Agent。Agent 官方不用于 Edge。
- 已配置至少一个模型提供者（Catalyst Agent 文档把这当作使用该模块任何功能的前提；纯 MCP 调用是否仍强制该前提，列为 CAT-01/CAT-04 实测项）。
- 已创建测试项目、模拟 Tag、测试用户与 API Key。记录 Gateway 完整 build、模块版本、edition、许可/试用状态。
- 运行容器前按官方 Docker 文档同意 EULA：`ACCEPT_IGNITION_EULA=Y`。本程序不代为拉取或启动镜像。

## 1. 得到真实 MCP 端点

- **Artek（已文档化）**：`http[s]://<gateway>:<port>/data/artek-mcp/mcp`。见 [Connect a client](https://docs.artek.io/mcp/connect/)。
- **Catalyst（不要猜路径）**：在 Gateway 打开 **Services > Catalyst > MCP Servers**，创建或选择服务，用 **Configure Primitives** 勾选要暴露的内置/自定义工具并保存，然后使用 **Copy Endpoint URL**。官方说明 Name 会出现在生成的 endpoint URL 中，但公开手册没有给出固定路径模板。

## 2. 传输与握手（引用 MCP 规范，而非猜测 Ignition 私有头）

依据 [MCP 2025-06-18 Streamable HTTP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) 与 [Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)、[Lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)：

1. 对 MCP 端点发 HTTP POST。`Accept` 必须同时包含 `application/json` 和 `text/event-stream`。请求体是单条 JSON-RPC 消息。
2. 先发 `initialize`（参数包括 `protocolVersion`、`capabilities`、`clientInfo`），再发 `notifications/initialized`。
3. 如果初始化响应带有 `Mcp-Session-Id`，后续请求必须带上该头。服务端若在此后返回 HTTP 404，必须重新 `initialize`。
4. 初始化完成后，后续请求应带 `MCP-Protocol-Version`，值为协商得到的版本（例如 `2025-06-18`）。
5. 然后发 `tools/list`。若结果含 `nextCursor`，用该游标继续请求，直到没有下一页。合并全部页后再保存。
6. 记录响应 `Content-Type` 是 `application/json` 还是 `text/event-stream`。两种都是规范允许的。
7. 可选：对同一端点发 HTTP GET。规范允许服务端返回 SSE 或 **405**。Artek 已文档化 GET 返回 405、无事件流；Catalyst 的 GET 行为必须实测，不得预先写成与 Artek 相同。

## 3. 认证：分别记录，不要把 REST 头直接当成 MCP 结论

### Artek（手册已写明）

每个 MCP POST 使用下列之一：

- `Authorization: Bearer <token>`
- `X-Artek-MCP-Token: <token>`

若启用 OAuth，则按 [Connect a client](https://docs.artek.io/mcp/connect/) 的 JWT 规则，不要与 API key 混用结论。

### Catalyst（手册未给出入站 MCP 的确定头名）

Catalyst Agent 的 MCP Server 权限说明提到：若设为 Public，则“all API tokens used by external MCP clients with the protocol endpoint will be given access permissions”。这把入站客户端与 **API tokens** 联系起来，但**没有写出 header 名称**。

因此采集时应分别试验并记录状态码、`WWW-Authenticate`（如有）和去敏后的响应体：

1. 无认证。
2. 官方 REST 文档使用的 `X-Ignition-API-Token: <api-key>`（见 [API Documentation](https://www.docs.inductiveautomation.com/docs/2027/platform/gateway/openapi)）。这是**待验证候选**，不是已证实的 MCP 头。
3. `Authorization: Bearer <api-key>`（同样只是候选）。
4. 若 Gateway 或响应提示了其他头，只记录实际观察到的名称，不要 invent。

同时记录该 API Key 的安全级别，以及 MCP Server 的 Permissions 是 Public 还是限定级别。不要把 MCP Server 设为 Public 理解成“无需凭据”。

## 4. 导出脱敏 fixture

每个环境保存一份 JSON，至少包含：

- Gateway 版本字符串、edition、Core/Agent 或 Artek 模块版本、许可或试用状态、操作系统/架构。
- 复制得到的 endpoint **路径模板**（可替换主机名为 `gateway.example.invalid`）。
- 实际成功的认证头**名称**（不保存 token 值）。
- `initialize` 结果中的 `protocolVersion`、`capabilities`、`serverInfo`；如有 `Mcp-Session-Id`，只记录“是否出现”和长度/格式类别，不保存原始 session id。
- 完整分页合并后的 `tools/list`：每个工具的 `name`、`title`（如有）、`description`、`inputSchema`、`outputSchema`（如有）、`annotations`（如有）。
- 工具来源标记：内置 `ignition/...`、某项目自定义工具、或 Artek provider。对照 Configure Primitives 勾选集合。
- HTTP 状态、内容类型、分页游标是否出现、GET 是否 405。

**必须删除**：API token、OAuth JWT、密码、cookie、`Mcp-Session-Id` 原值、真实主机名/内网 IP、用户名、会暴露现场的 Tag 路径或项目内容。Schema 里若误含示例密钥，一并替换。

建议文件名：

- `docs/evidence/runtime/8.3.9-artek-mcp-tools.redacted.json`
- `docs/evidence/runtime/2027.2.0-beta1-catalyst-mcp-tools.redacted.json`

本轮研究**没有**产生这些 runtime 文件。

## 5. 可选但建议同时采集的 OpenAPI

同一 Gateway 以同样的 API Key 获取：

- `GET /openapi.json`（官方文档的机器可读规格；文档写明多数路由需要 `X-Ignition-API-Token`）
- 需要时保存 `/openapi` 页面的版本信息

这是 CAT-09 / 8.3 对等项。规格随已安装模块动态生成，不要用一份静态猜的清单代替。导出后删除 token，可替换 host。不要把配置资源路径想当然推广为任意 Perspective View 的读写 API。
