# 研究补充：四个剩余阻塞项（2026-11-17）

补充日期：2026-11-17（Asia/Singapore，UTC+8）。本文件是对已有 [深入技术调查](https://github.com/Sentheecode/ignition-harness/blob/main/docs/technical-investigation.md)、[Catalyst 专项调研](https://github.com/Sentheecode/ignition-harness/blob/main/docs/catalyst-research.md) 与 [验证路线](https://github.com/Sentheecode/ignition-harness/blob/main/docs/validation-roadmap.md) 的**增量补充**，不改写那些文件的历史结论。

资料范围：公开的 Inductive Automation 2027.02 Beta / 8.3 手册、Artek 工具与行为手册、MCP 规范、Docker Hub 标签元数据，以及仓库中已有的 `2027.2.0-beta1` SDK Javadoc 证据。正文区分：

- **(A) 有出处的文档事实**
- **(B) 技术推论**（单独标明）
- **(C) 仍未核实**（包括一切需要实机 Gateway 的事项）

**本轮没有启动或配置 Gateway，没有执行 MCP `initialize` / `tools/list`，没有进行资源写入或登录运行测试，也没有拉取 Docker 镜像。** 仓库状态仍是调研阶段，不应开始堆砌产品页面。

已知且本轮不推翻的结论：MCP 工具调用、工程资源写入、实时 Tag 订阅、用户登录和 Perspective 预览是不同通道；Artek `tag_write` 写的是值；Artek MCP 无状态、GET 405、无事件流；Catalyst Designer 工具/上下文不是自动的外部远程 Designer API；DeepSeek Harness 浏览器分区默认不跨重启持久化；8.x 模块必须针对 2027 重新构建。

## 1. Catalyst MCP Server 的实际工具清单

### (A) 已能从公开资料确认的事实

官方 [Catalyst Agent](https://www.docs.inductiveautomation.com/docs/2027/ignition-modules/catalyst/catalyst-agent) 手册（页面标注 2027.02 Beta，Markdown 源 last-modified 2026-11-10）写明：

- 模块用 **Streamable HTTP** 实现 MCP。
- 外部客户端应连接 **Services > Catalyst > MCP Servers** 中创建的服务，而不是 **MCP Connections**（后者是 Gateway 出站客户端）。
- 创建服务后，用 **Configure Primitives** 勾选工具并保存，再用 **Copy Endpoint URL** 交给外部客户端。Name 会进入生成的 endpoint URL 和文件系统存储；公开手册**没有**给出可抄写的固定路径模板。
- Configure Primitives “lists the custom and built-in Designer tools”。自定义工具按**项目名**列出；内置工具在 `ignition` 分组下。
- MCP Server 具有独立的会话参数：Max Sessions 默认 100，Max Lifetime 默认 120 分钟（`0` 表示不限制），Idle Timeout 默认 30 分钟（`0` 表示不限制）。这是 **MCP 会话**，不是 Designer 或 Perspective 用户登录。
- 权限说明提到：若设为 Public，则 “all API tokens used by external MCP clients with the protocol endpoint will be given access permissions”。手册把入站 MCP 与 **API tokens** 联系起来，但**没有写出请求头名称**。
- Agent 模块依赖同 Gateway 上的 Catalyst Core，并且文档要求至少配置一个模型提供者才能使用该模块的任何功能。Agent 兼容 Standard、Cloud、Maker，**不用于 Edge**（见 [Catalyst 总览](https://www.docs.inductiveautomation.com/docs/2027/ignition-modules/catalyst) 与升级指南 “The Catalyst Agent module is not available in Ignition Edge.”）。
- 升级指南还写：Catalyst agents 和 MCP connections 在新安装上默认是 **Authenticated** 访问。该句针对的是 agents 与（出站）MCP connections，不能直接当成入站 MCP Server 的默认权限结论。

同一手册引用的官方截图 [configure-primitives-panel](https://docs.inductiveautomation.com/assets/images/configure-primitives-panel-14ba3d6cce6be590ceb25358ac7d5bcd.png) 在 2026-11-17 仍可访问。本轮记录了字节数、SHA-256 和可见文案，见 [evidence/configure-primitives-screenshot-2026-11-17.json](evidence/configure-primitives-screenshot-2026-11-17.json)。截图窗口标题为 “Configure Test_Server Primitives”，过滤框为空白。可见分组只有：

| 分组 | 显示名 | 截图中的说明（原文） |
|---|---|---|
| `ignition/tags` | `realtime` | Reads live tag values directly from the tag subsystem, returning value, quality, timestamp, and valueType for each requested path. |
| `ignition/tags` | `query` | Queries the tag provider for all matching tags. Each result gives the tag's fullPath and tagKind. For a value-holding tag,（其后在截图中被截断） |
| `ignition/tags` | `providers` | Returns the available tag providers for querying tags |
| `ignition/tags` | `diagnostics` | Returns the diagnostics for the provided path |
| `project/samplequickstart` | `Test` | Test MCP Server Implementation（项目自定义工具） |

最后一组下方有大片空白。这是该截图**画面内**的清单，不是 `tools/list` 导出。

仓库已有的 Beta1 SDK 证据仍然有效：`DesignerToolFactory` 的八个 bundle（`systemLibrary`、`userLibrary`、`tagConfigRead`、`opcBrowse`、`datasource`、`gatewayConfig`、`project`、`designerState`）以及 `DesignableProjectTools` 的读取方法，都是 **Java API / Designer 宿主工具**，不是已证实的 Gateway MCP wire 名。`GatewayAiContext.mcpToolsFor(...)` 文档含义是为 Gateway Agent **消费出站 MCP 工具**，不能理解为自动对外发布全部 Java 方法。这些判断与本轮手册一致，无需修正。

在公开手册、官方论坛检索和第三方页面中，**没有找到**一份标明 2027.2.0-beta1、由 Gateway MCP Server 返回的完整 `tools/list`（含 schema 与分页）。第三方 community MCP 项目（例如各种 `ignition-mcp-server`）的工具名**不得**当作 Catalyst 内置工具。

### (B) 技术推论

1. 截图里 `ignition/tags` 四个条目的说明都是读取、查询、列出提供者或诊断，没有写出写入、创建 Tag 或修改项目资源。若某台 Gateway 的 Configure Primitives 画面确实只有这一组内置工具，则该 MCP Server 默认内置面可能偏 OT 读取，而不是远程 Designer。这**不能**升级为“Beta1 没有项目写入工具”：可能因模块组合、截图选题或后续 build 而不同；自定义 Designer 脚本工具仍可被勾选暴露。
2. 官方把 Configure Primitives 中的内置项称为 “built-in Designer tools”，同时又把它们放在 Gateway MCP Server 的暴露列表里。名称上的 “Designer” 不证明这些工具自动携带 Designer 选中对象、编辑器状态或 Apply 流程。这一点与专项调研第 3 节一致。
3. `realtime` 的说明是“读取实时值并返回 value/quality/timestamp/valueType”，从文案看是一次工具调用读取，**不足以**证明存在可持续的 Tag 订阅或 SSE 事件流。

### (C) 仍未核实

- 2027.2.0-beta1 实机 `initialize` 与分页 `tools/list` 的完整 wire 清单与 schema。
- 显示名与 wire `name` 的对应关系（例如是否叫 `ignition/tags/realtime` 或其他形式）。
- 完整安装（Perspective、数据库、Gateway 配置等模块齐备）时，是否还有未出现在该截图中的 `ignition/...` 分组。
- 入站 MCP 的实际认证头、401/403 行为，以及安全级别如何传递到工具执行。
- 纯 MCP 调用是否仍要求已配置模型提供者，以及是否会触发 Gateway 侧模型计费（CAT-01、CAT-04）。
- GET 同一 endpoint 是返回 SSE 还是 405；`Mcp-Session-Id` 与手册中 Max Lifetime / Idle Timeout 的实际关系。

**没有实机 Gateway，就无法得到完整 wire 级工具清单。** 精确采集步骤见 [evidence/catalyst-mcp-collection-procedure-2026-11-17.md](evidence/catalyst-mcp-collection-procedure-2026-11-17.md)。

## 2. 外部工程登录与会话续期

### (A) 已能从公开资料确认的事实

官方文档把几种身份机制分开描述，没有把它们写成同一个外部登录 API。

**Designer 登录（交互式，发生在 Designer 产品内）：**

- [Gateway General Security Settings](https://www.docs.inductiveautomation.com/docs/2027/platform/security/gateway-general-security-settings)（2027 与 [8.3 对应页](https://www.docs.inductiveautomation.com/docs/8.3/platform/security/gateway-general-security-settings) 均存在）：Designer Authentication Strategy 为 **Classic** 或 **Identity Provider**。
- Classic：用户在 Designer **内嵌登录表单**输入用户名和密码，相对 **System User Source** 认证；可配置允许的 Designer 角色；可选 SSO（若该 User Source 支持）。见同页及 [Classic Authentication Strategy](https://www.docs.inductiveautomation.com/docs/2027/platform/security/classic-authentication-strategy)。
- Identity Provider：将用户重定向到浏览器中的 IdP；由 System Identity Provider 决定目标。见 [Identity Provider Authentication Strategy](https://www.docs.inductiveautomation.com/docs/2027/platform/security/identity-provider-authentication-strategy)。
- 2027 升级指南新增：同一 Gateway 或项目可配置**多个** Identity Provider，登录时可出现选择页。8.3 的单一 IdP 设置会自动迁移。

**Designer / Vision 的 IdP auth token 恢复（官方描述的是客户端内存中的恢复令牌，不是公开的第三方登录 API）：**

- 登录 IdP 后，Gateway 会话会生成特殊 auth token，保存在 **Designer 和 Vision Client 实例内存**中；连接丢失后可用有效 token 恢复，而不必完全重启。
- auth token **不包含在 Gateway 备份中**；恢复备份会清除现有 token。
- Designer 的 User Inactivity Timeout 默认 10 分钟（必须大于 0）；TTL 默认 0 表示除因不活动过期外可不限期。这些设置在 Classic 策略下不适用。
- 公开手册没有为第三方工作台提供获取、刷新或校验该 auth token 的 HTTP 接口说明。

**项目级 Designer 权限：**

- [Project Security in the Designer](https://www.docs.inductiveautomation.com/docs/2027/platform/security/project-security-in-the-designer) 描述 View / Save / Delete / Protect Resources 所需角色。Designer 不轮询角色变更，已登录用户需重新启动 Designer 才能获得新角色。这是 Designer 产品行为，不是外部 API。

**官方对外的机器访问凭据是 API Key，明确用于非交互式 HTTP API：**

- [API Keys](https://www.docs.inductiveautomation.com/docs/2027/platform/security/api-keys)（8.3 对应页同样存在）：API Key 用于“无需交互式用户认证”地访问 Gateway HTTP API。
- 创建时只显示一次明文；Gateway 只保存哈希。可附加安全级别；默认要求安全连接。
- 文档规定，在 **Gateway API Documentation（`/openapi`）所记录的路由**上，请求头为 `X-Ignition-API-Token: <token>`。
- 手册警告：API Keys 可授予对 HTTP API 的广泛权限，包括修改配置、Tag 和项目。这与“用户完成了 Designer 身份登录”不是同一件事。产品需求已要求不能用一个管理员 API key 冒充完成 Designer 登录，这一点仍然成立。

**OpenAPI 明确排除了一类路由：**

- [API Documentation](https://www.docs.inductiveautomation.com/docs/2027/platform/gateway/openapi)：“Only routes that are explicitly documented by installed modules will appear in the API documentation. **Internal or session-dependent routes are excluded.**”
- 因此，即便 Designer 或 Gateway 网页内部存在会话相关 HTTP 调用，它们也**不在**这份对外规格里，不能被当作稳定的第三方合同。

**Gateway 网页会话与 Perspective 会话是另外的通道：**

- Gateway General Security Settings 中的 User Inactivity Timeout 作用于 **Gateway web interface session**。
- [Security in Perspective](https://www.docs.inductiveautomation.com/docs/2027/ignition-modules/perspective/security-in-perspective) 写明 Perspective 安全通过 IdP 管理；项目属性中选择 IdP，并在 Perspective Permissions 中授予会话访问。
- [system.perspective.login](https://www.docs.inductiveautomation.com/docs/2027/appendix/scripting-functions/system-perspective/system-perspective-login) 在已有 Perspective 会话中触发项目 IdP 登录。它是脚本函数，不是给外部工作台调用的登录 HTTP API。
- 升级指南写道：`system.perspective.login` 在 2027 增加了 `idp` 参数。本轮打开的函数页（页面脚注 last updated 2024-09-25）**尚未在已发布签名表中列出 `idp`**。这是文档不一致，运行签名以实机/该 build 的脚本函数文档或实际调用为准，本文不编造参数表。

**Catalyst MCP 会话 ≠ 用户登录。** 第 1 节的 Max Lifetime / Idle Timeout 管理的是 MCP 会话。

在 2027 与 8.3 安全手册、API 手册和已收录的 Beta1 SDK 重点类中，本轮**没有找到**名为 Designer login / session refresh、可供第三方工作台稳定调用的官方外部 API。

### (B) 技术推论

把需求里的四种状态对应到**已文档化的机制**（对应的是机制，不是“已经能由本产品调用”）：

| 状态 | 文档中对应的机制 | 第三方工作台目前能依据什么 |
|---|---|---|
| 工程身份有效 | Designer Classic 表单或 Designer IdP 浏览器重定向；项目级 Designer 角色；IdP auth token 仅描述为 Designer/Vision 内存恢复 | 未找到稳定官方外部登录/续期 API。不能把实现写成“调用 Designer login API”。API Key 不能冒充该身份。 |
| MCP 可调用 | Artek：文档化的 API key / 可选 OAuth。Catalyst：与 API tokens 相关联，头名待实测 | 这是服务凭据，不是 Designer 用户会话。过期与权限失败应单独显示。 |
| 实时订阅在线 | SDK 进程内 `TagManager.subscribeAsync`；Artek 明确无事件流；Catalyst `realtime` 工具从文案看是读取 | 尚无已证实的对外订阅协议。有连接的 MCP 不等于订阅在线。 |
| Perspective 已登录 | 项目 IdP + 浏览器会话；`system.perspective.login` 只作用于已有会话 | 工作台内真实浏览器 profile 完成 IdP/登录跳转。不继承 API Key 或 MCP 已认证的结论。 |

若产品仍要求“添加项目时类似 Designer 登录，并在重启后恢复”，在缺少官方外部登录 API 的前提下，比较务实的方向是：对 Gateway 网页 / IdP / Perspective 使用**真实浏览器交互登录**，并把 cookie/storage 保存在按 Gateway + 工程身份隔离的持久分区（这恰好也是必须改造 DSH 默认非 `persist:` 分区的原因）；MCP 与 REST 使用单独的 API token，四种状态分开显示。这是产品/实现建议，不是发现了隐藏的 Designer 协议。

为第三方复刻 Designer 私有握手或从 Designer 进程提取 auth token，没有官方合同，也不应作为本项目路线。

### (C) 仍未核实

- 是否存在未收入 OpenAPI 的内部 Designer 登录/续期协议（即便存在，也不等于稳定官方外部 API）。
- Classic 与 IdP 在 8.3.9 与 2027.2.0-beta1 上的浏览器跳转、cookie、iframe/`webContents` 限制。
- API Key 是否会被绑定到某个 Ignition 用户主体，以及审计中的 actor 格式（升级指南给出示例 `usr-prov:default:/usr:admin` 或 `idp:` 前缀）在 API Key 调用下的实际值。
- Catalyst MCP 会话超时后，是否必须重新 `initialize`，以及这与用户 IdP 会话的关系（预期应相互独立，但需实测）。

## 3. Gateway Companion 是否必要

能力对照的完整表格见 [capability-gap-matrix.md](capability-gap-matrix.md)。这里只给结论和使用条件。

### (A) 与缺口直接相关的文档事实

- **Artek 手册已点名**一批与需求相关的工具：项目资源读写（`project_resource_write`、`view_patch`）、Gateway 配置读写、Tag 浏览/读值/读配置/`tag_write`（值）、UDT 定义读取、数据库（默认关闭）、以及 `api_discover` / `api_call` REST 桥。权威清单仍是运行时的 `artek-mcp://tools`。tags 表中**没有**名为新建 Tag/UDT 或 `tag_config_write` 的工具。行为手册再次确认服务无状态、GET 405、无事件推送。
- **Catalyst MCP** 目前只证实存在可勾选的内置 `ignition` 分组和项目自定义工具；截图可见的内置项是 `ignition/tags` 的四项读取/查询/诊断。项目写入、Tag 配置写入是否出现在 Beta1 的 MCP 清单中，仍属 (C)。
- **官方 Gateway HTTP API** 从 8.3 起把许多**配置资源**暴露在 `/data/api/v1/resources` 下，并给出路径模式，例如 `GET /data/api/v1/resources/list/<moduleId>/<typeId>`、`POST /data/api/v1/resources/<moduleId>/<typeId>`、`DELETE /data/api/v1/resources/<moduleId>/<typeId>/<collection>/<name>`。API Keys 页还提到 `/data/api/v1/sync` 与 `/data/api/v1/modes`。[system.config](https://www.docs.inductiveautomation.com/docs/2027/appendix/scripting-functions/system-config) 的警示表还给出若干**真实路径**（作为应谨慎调用的例子）：`POST /data/api/v1/scan-lock/config`、`POST /data/api/v1/scan-lock/projects`、`POST /data/api/v1/scan/config`、`POST /data/api/v1/scan/projects`、`POST /data/api/v1/restart-tasks/restart`、`POST /data/api/v1/diagnostics/bundle/generate`。完整清单只能来自目标 Gateway 的 `/openapi.json`。手册把这些路由描述为配置资源 / 配置管理，**没有**在静态手册里列出 Perspective View 项目资源的专用 REST 合同。
- **Beta1 SDK**（已有证据）在 Gateway 进程内提供 `ResourceCollectionManager.push/pull`（带过期签名冲突）、`TagProvider.saveTagConfigsAsync`、`TagManager.subscribeAsync`、`GatewayTagManager.addTagStructureListener`。这些是模块/Companion 可以调用的平台 API，不是外部 HTTP/MCP 工具名。
- **脚本封装是另一条已文档化的能力**：2027 的 [system.tag.configure](https://www.docs.inductiveautomation.com/docs/2027/appendix/scripting-functions/system-tag/system-tag-configure) 可用于创建/更新 Tag 配置；Catalyst 允许在 Designer 中把脚本发布为带权限的自定义工具。这不是内置 MCP 工具，也尚未在实机上验证。
- 升级指南（原文）：“Module compatibility is now based on the year version. **Modules built for Ignition 8.x will fault on a 2027 Gateway.** Additionally, a module built for a newer 2027 release will fault on a Gateway running an older 2027 release.” 第三方模块必须有明确兼容 2027 的版本。因此任何 Companion 都要按 8.3 与 2027 **分别构建**，且不能假设一个 2027 Companion 可以用于所有 2027 小版本。

### (B) 结论（研究建议，非已批准设计）

| 判断 | 说明 |
|---|---|
| **现在不必做 Companion** | 当前阻塞是实机工具清单、登录协议边界和写入验证，不是缺少一个尚未设计的模块。没有这些证据就开工 Companion，会把假设写进产品。 |
| **8.3 上很可能暂不需要 Companion 才能开始有限工程闭环** | 若实机证实 Artek 的 `project_resource_write` / `view_patch` / `config_resource_*` 行为与手册一致，画面、脚本和 Gateway 配置的“直接写回 Gateway”可以先走 Artek（外加官方 REST 中已发现并验证的配置路由）。这仍取决于运行验证。 |
| **稍后很可能需要**（两个版本都可能） | **实时 Tag 树与值推送**：Artek 明确无事件流；Catalyst 截图中的 `realtime` 从文案看是读取；公开手册没有给出对外的 Tag 订阅协议。SDK 订阅 API 存在于 Gateway 进程内，这是 Companion 最清楚的候选理由。 |
| **稍后很可能需要，但先要查完 OpenAPI / 自定义工具** | **新建 Tag / UDT（尤其 8.3）**：Artek 手册未提供对应工具。2027 可用自定义工具封装 `system.tag.configure`，或在 `/openapi.json` 中寻找经证实的 Tag 配置路由。只有这两者都不够时，才应用 Companion 调用 `saveTagConfigsAsync`。 |
| **不能靠 Companion 发明官方登录 API** | 若产品坚持 Designer 同款身份映射，Companion 顶多提供受控的认证映射（仍要走官方 IdP/用户源，并做安全审查）。它不会让“Designer login API”在官方文档里出现。在官方外部登录 API 仍缺失的情况下，优先用持久浏览器身份，而不是先写登录模块。 |

**现在不需要**用 Companion 来：浏览项目列表（Artek 已有 `projects_list`）、在工作台内做 Perspective 预览（走真实浏览器会话）、或在已验证的前提下读写 8.3 的项目资源与 Gateway 配置。

### (C) 仍未核实

- 目标 Gateway 的 `/openapi.json` 是否包含 Tag 配置或项目资源（View/脚本）的可写路由。
- Catalyst 自定义工具封装 `system.tag.configure` / 资源写入的权限、校验和冲突行为。
- 若将来做 Companion，push 冲突、结构监听和订阅在两个目标版本上的实际表现。

## 4. 写入 / 刷新运行验证计划（仍需实机，不编造结果）

先前的 P0 与 CAT-01～CAT-10、以及技术调查第 9 节的连续场景仍然有效。本节省在把环境证据、许可限制和采集步骤写得可执行，而不是覆盖那些清单。

### 环境与许可（(A)）

Docker Hub 在 2026-11-17 查询到（只查标签元数据，未拉镜像），详见 [evidence/docker-tags-2026-11-17.json](evidence/docker-tags-2026-11-17.json)：

| 标签 | 状态 | 架构与 digest | 标签最近更新（已换算） |
|---|---|---|---|
| `inductiveautomation/ignition:2027.2.0-beta1` | active | linux/amd64 `sha256:8893fd9065ebb48965fa249dadbd11d48bb4edbd2047272889d411c7ab4b76c9`；linux/arm64 `sha256:d3489b97264f242ffaef1af8c8b9ab1ee5a4f92f361f6fcc0f80f56cde8afc89` | 2026-11-04 08:28:38 Asia/Singapore（UTC+8） |
| `inductiveautomation/ignition:8.3.9` | active | linux/amd64、linux/arm64，以及 arm/v7 | 2026-08-26 06:28:10 Asia/Singapore（UTC+8） |

amd64 的 Beta1 digest 与仓库技术调查已记录的值一致。

注意：2027 [Docker Image](https://www.docs.inductiveautomation.com/docs/2027/platform/advanced-deployments/docker-image) 通用页仍列出 linux/arm/v7，但 **`2027.2.0-beta1` 标签元数据没有 arm/v7**。升级指南说明 2027 捆绑 Java 25，不支持 32-bit ARM。验证应使用 amd64 或 arm64。运行镜像需 `ACCEPT_IGNITION_EULA=Y`，使用受 Inductive Automation Software License Agreement 约束。

许可与 edition：

- 升级指南：**不要把任何生产 Gateway 升级到 Ignition 2027，直到正式版发布。Beta 只用于开发或测试系统。**
- 升级指南：**现有许可证与 2027 Beta 不兼容。** 正式发布后需向销售确认 2027 就绪的许可证。
- [Licensing and Activation](https://www.docs.inductiveautomation.com/docs/2027/platform/licensing-and-activation)：未许可模块按试用运行，约两小时后停止；可在 Gateway 上多次 Reset Trial。Gateway 网页和 Designer 不受该试用定时器影响。Perspective 会话会显示试用状态。验证计划必须记录试用重置，避免把模块停走误判为产品缺陷。
- Catalyst Agent 不能作为 Edge 路径承诺。Core 的 edition 覆盖面更广，但不能据此假设 Agent/MCP 在 Edge 可用。
- 官方 SDK 示例仓库的 `docker-compose.yml` 在已记录的 commit 上仍为 `8.1.26`，不可不经修改当作 Beta 或 8.3.9 测试环境。

### 用户必须提供的东西

1. 隔离的开发/测试主机或同意在本机运行官方镜像（本轮研究未启动任何容器）。
2. 如需避免两小时试用中断：适用于该 build 的开发许可（2027 Beta 可能无法使用现有 8.x 许可）。
3. 管理员测试用户、用于 MCP/REST 的 API Key、Artek 模块文件（不把第三方 `.modl` 提交进本仓库）、以及 2027 上已安装的 Catalyst Core/Agent。
4. 一个可回滚的测试项目：Memory Tag、Perspective View、项目库脚本、Named Query、一条可恢复的 Gateway 配置。不要连生产设备。
5. 同意把脱敏后的 `tools/list` 与 `/openapi.json` 片段提交为证据。

### 建议执行顺序（细化，不替换 CAT-01～CAT-10）

对 **8.3.9+Artek** 与 **2027.2.0-beta1+Catalyst** **分别**走完整路径，不得用其中一条的结果代替另一条。

1. 安装与依赖：CAT-01 及 Artek 对等项。记录模块是否故障（尤其是把 8.x 模块装进 2027 的负向检查）。
2. 按 [采集程序](evidence/catalyst-mcp-collection-procedure-2026-11-17.md) 导出脱敏 `initialize` + 分页 `tools/list`（P0.1 / CAT-02）。Artek 同时保存 `artek-mcp://tools`（若可读）。
3. 认证矩阵：CAT-03。Artek 按手册验证 Bearer / `X-Artek-MCP-Token` 与 readOnly/allowlist。Catalyst 只记录实测成功的头。
4. 同一 Gateway 导出脱敏 `/openapi.json`（CAT-09）。只从规格中挑选后续要调用的路由。
5. 只读往返：View、Style、脚本、项目配置（P0.2 / CAT-05）。保留未知字段。
6. 单 View 修改、写入、重读、真实 Perspective 预览、恢复（P0.3 / CAT-06）。这是连通性门槛，不是完整 MVP。
7. 技术调查第 9 节的连续场景：登录与重启恢复、新建 Memory Tag（配置与值分开）、绑到新 View、项目库与 Gateway 事件脚本、可回退的配置修改、数据库分页、冲突拒绝与超时读回。
8. 中断、权限不足、模块停用、schema 变化、试用到期（P0.6 / CAT-07 / CAT-08）。未确认的写入不得自动重放。

验收物与原路线一致：版本清单、脱敏 schema、前后快照与 hash、调用结果、重读结果、真实会话截图。只有截图不能证明写入正确。

## 5. 对建议路线的更新

不改变“先研究清楚再开发、先验证再堆 UI”的原则。根据本轮证据，把路线收紧为：

1. **先提交本补充包**（本目录是待提交材料，本轮执行器不克隆、不推送仓库）。
2. **在用户提供隔离 Gateway 之前，允许做的准备工作**（仍不是产品 UI）：采集/脱敏脚本、本验证计划的可执行清单、DSH 持久浏览器分区的设计说明、按实际工具映射的适配器接口草稿（接口保持空实现或对未验证工具失败）。
3. **一有测试 Gateway，立刻采集** 两份脱敏 `tools/list` 和两份 `/openapi.json`。没有这两项，不得宣称 Catalyst 能或不能写项目资源。
4. **8.3 适配优先以 Artek 手册中已点名的工具为准**，用实机确认写入、继承保护和冲突行为。2027 以实测 MCP 清单为准；若内置工具不够，再评估经权限约束的自定义工具，然后才是已证实的 OpenAPI 路由。
5. **登录体验走持久浏览器 profile + 分状态指示**，直到出现官方外部工程登录 API（目前没有）。不要实现“Designer login 客户端”。
6. **Companion 推迟到运行证据证明公开通道无法覆盖实时订阅和/或 Tag 配置写入。** 若要做，8.3 与 2027 分别构建。
7. 只有在至少一条版本路径上完成 CAT-06（单 View 写入 + 真实预览 + 恢复），并且四种连接状态的含义已经能向用户讲清楚之后，才进入 DSH distribution + 领域插件的最小实现。此时仍先做连接、能力发现、资源读写与预览生命周期，而不是完整的 Designer 替代界面。

## 6. 本轮之后仍阻塞产品实现的事项

1. **2027.2.0-beta1 Catalyst MCP 的实机 `tools/list`（含 schema 与分页）**，以及入站认证头。公开资料无法补完。
2. **两个目标版本上的写入/刷新/冲突/预览运行验证。**
3. **官方外部 Designer 级登录/续期 API：本轮未找到。** 若未来也没有，产品必须接受浏览器持久登录 + 分离的 MCP/REST 凭据，而不是等待一个未文档化的协议。
4. **目标 Gateway 的实际 `/openapi.json`**，用于判断 REST 能补哪些缺口。
5. **用户提供的隔离测试 Gateway、EULA 同意，以及（如需要）可用于 2027 Beta 的开发许可。**

这些问题未解开前，不应开始堆砌产品页面，也不应安排以实现完整工作台为目标的编码工作。可以把采集脚本和验证脚手架视为研究的延续，而不是产品交付。
