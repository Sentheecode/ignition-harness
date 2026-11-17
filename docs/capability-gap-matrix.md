# 能力缺口矩阵：REQ-01～REQ-10

日期：2026-11-17（Asia/Singapore）。对照 [产品范围](https://github.com/Sentheecode/ignition-harness/blob/main/docs/product-requirements.md)。

图例：

- **手册已描述**：公开供应商/官方文档点名了该能力（仍需实机确认行为）。
- **仅 SDK / 仅脚本**：存在平台 Java API 或脚本函数，但不是现成的外部工具。
- **截图线索**：只在官方 Configure Primitives 截图中见到显示名，不是 wire schema。
- **未证实**：公开资料不足以判断存在或缺失。
- **不适用 / 工作台本地**：主要在客户端完成，不依赖某条 Gateway 协议。

不要把某一格的“手册已描述”写成“已经在本项目中验证通过”。本轮没有运行 Gateway。

Companion 总判断见补充报告第 3 节：现在不必做；实时订阅以及（在 OpenAPI/自定义工具仍不够时）Tag/UDT 创建很可能稍后需要；不能靠 Companion 发明官方登录 API。

## 总表

| 需求 | Artek MCP（手册，8.3.4+ 模块门槛；产品基线 8.3.9） | Catalyst MCP / 公开 2027 手册 + 截图 | 已文档化的 Gateway REST / OpenAPI | Beta1 SDK 或官方脚本（进程内 / 自定义工具候选） | Companion |
|---|---|---|---|---|---|
| REQ-01 左侧 Project 栏，多 Gateway、显示当前目标 | 手册有 `projects_list`、`project_resources`；资源 `ignition://gateway/projects` 含继承关系。栏本身是本地 UI。 | 未证实有项目枚举内置工具。截图未见项目浏览分组。 | 手册未给出“列出全部项目”的静态专用合同。`/openapi.json` 待采集。 | 未在已收录证据中单独引用对应外部 API。 | **现在不需要**（本地栏 + 已文档化的项目列表工具，或实测后的等价物）。 |
| REQ-02 类似 Designer 的交互登录，并保存状态 | Artek 认证是 API key 或可选 OAuth，不是 Designer 用户登录。设置页使用 Gateway 网页会话，与 MCP key 分开。 | 入站 MCP 与 “API tokens” 相关联，头名未写明。不是 Designer 登录。 | 官方对外机器认证是 API Key + `X-Ignition-API-Token`（用于已文档化的 HTTP API）。手册写明 API Key 用于非交互访问。OpenAPI **排除** internal / session-dependent 路由。 | 无已收录的外部 Designer 登录 API。Designer IdP auth token 只描述为 Designer/Vision 内存恢复。 | **现在不需要**。也**不能**用模块“补出一个官方 Designer login API”。优先持久浏览器身份。身份映射若仍缺官方 API，属**稍后、需安全审查**的可能项。 |
| REQ-03 长期会话：切面板不掉线，服从服务器有效期 | 服务**无状态**；无 MCP 会话可续期。工具/profile 变化后要重连。不能把 MCP 连接当成长期工程会话。 | 手册有 MCP Session：默认 Max Lifetime 120 分钟、Idle Timeout 30 分钟、Max Sessions 100。这是 MCP 会话寿命，不是用户登录。 | API Key 本身不是带 TTL 刷新的用户会话（文档未把它描述为可刷新的用户 token）。 | Designer IdP auth token 有 inactivity / TTL 设置，但是客户端产品行为。 | **现在不需要**才能继续研究。若要统一“工程会话”心跳，应先实测各通道超时，再决定是否要模块。 |
| REQ-04 新增及修改点位（配置与值分开） | **值**：`tag_write`（手册，mutating，最多 50 对路径/值）。**读配置**：`tag_config_read`、`udt_types_list`、`udt_definition_read`、`tag_browse`、`tag_read`。**新建 Tag/UDT**：tags 表中**未见**对应写入工具。 | 截图有 `ignition/tags`：`realtime`、`query`、`providers`、`diagnostics`（文案均为读/查/诊断）。写入与创建未证实。 | 静态手册没有给出 Tag 配置 REST 路径。可能出现在实机 `/openapi.json` 中，列为待采集。 | `TagProvider.saveTagConfigsAsync`、`writeAsync`；脚本 `system.tag.configure` / `system.tag.getConfiguration`（后者会省略默认属性）。可考虑封装为 Catalyst 自定义工具。 | **现在不必做**。若实机 OpenAPI 与自定义工具都无法安全创建 Tag/UDT，则 **稍后很可能需要**（调用 SDK 配置写入）。 |
| REQ-05 新增及修改画面，直接写回 Gateway | 手册有 `project_resource_write`、`view_patch`（保留 null 键）、`project_resource_delete`（name echo）。继承资源写入会检查定义方。语法校验针对 `.py` 与 `.json`；不自动等于组件语义正确。 | 未证实有 View 写入内置工具。自定义脚本工具可以勾选暴露，行为未测。截图未见画面编辑分组。 | 手册将 `/data/api/v1/resources` 描述为**配置资源**。没有静态的 Perspective View REST 合同。不可把配置资源模式外推为 View 读写。 | `ResourceCollectionManager.push/pull/pushPartial`，带过期签名冲突。`DesignableProjectTools` 为 Designer 内读取，依赖 `DesignableProject`。 | **现在不需要**作为 8.3 的第一选择（先验证 Artek 写入）。2027 取决于 MCP/OpenAPI 实测；只有二者都不够时再考虑。 |
| REQ-06 新增及修改脚本（项目库、Gateway 事件、组件脚本） | 走 `project_resource_write`（`.py` 会做语法校验）。不同宿主的资源标识需实机确认。`deploy_apply` **不做**同样的内容校验。 | 同 REQ-05：内置写入未证实；自定义工具未测。 | 同 REQ-05：没有静态项目脚本 REST 合同。 | 同 REQ-05，push/pull。脚本宿主生命周期仍需运行验证。 | 与 REQ-05 相同。 |
| REQ-07 在工作台内操作 Gateway Web 配置；未覆盖页可内置浏览器打开 | 手册有 `config_types`、`config_resources`、`config_resource_read`（secret 始终脱敏）、`config_resource_write`（拒绝含脱敏标记的内容；按类型热应用或需重启）、`config_manifest`。模块自身设置除外。 | 未证实有配置写入内置工具。SDK 中 `GatewayConfigTools` 是 Designer 只读浏览 bundle。 | **手册已描述**配置资源 CRUD 模式：`/data/api/v1/resources/list/{module}/{type}` 等，以及 `/data/api/v1/sync`、`/data/api/v1/modes`。警示表中的扫描/锁/重启路径见补充报告第 3 节。认证头：`X-Ignition-API-Token`。 | 未在本矩阵把未收录的 Java 配置 API 写成已证实外部接口。 | **现在不需要**（Artek 配置工具 + 官方配置 REST + 内置浏览器作为兜底，均需实机确认写回与重启反馈）。 |
| REQ-08 内置浏览器实时预览 Perspective | `list_perspective_sessions` / `get_session_details` 是**会话监控**，不是渲染或登录。`close_session` / `send_session_message` 为高风险 mutating，与预览不是同一功能。 | 无预览工具证据。Perspective AI Chat 是运行时助手，不是预览引擎。 | 无“打开预览会话”的 REST 合同被静态列出。 | 不适用。预览应使用真实 Perspective 会话 URL。 | **不需要**做预览引擎。需要改造的是工作台浏览器持久分区（DSH 默认非 `persist:`），这是桌面壳改动，不是 Gateway 模块。 |
| REQ-09 Tag 树、点位值、数据库预览（按需订阅/刷新/分页，操作后同步） | Tag：浏览/读值/读配置，有上限（browse 500、read 100）。**无事件流**。数据库：`db` 提供者默认关闭，只读 SELECT / Named Query 需单独开启。 | 截图 `realtime` / `query` / `providers` 是工具读取线索，不是已证实的订阅。数据库工具未在截图中出现。 | 配置资源 API 不能代替数据库浏览。具体查询路由待 `/openapi.json`。Artek `api_call` 必须先发现路由。 | `subscribeAsync` / `unsubscribeAsync`；`addTagStructureListener`（结构变化，不含初始树）。这是 Companion 或进程内桥的主要 API 依据。 | **稍后很可能需要**，用于真正的值与结构推送。早期可用有界轮询，但不得把轮询宣称为实时订阅。数据库浏览优先走已配置的 Gateway 数据源（经已验证的 MCP/REST），不要另建身份不明的直连。 |
| REQ-10 先研究清楚再开发 | 本补充与既有调查文件。权威工具表仍待实机 `artek-mcp://tools` 或 `tools/list`。 | 缺 Beta1 `tools/list`。采集程序已写。 | 缺目标 Gateway 的 `/openapi.json`。 | SDK 静态证据已在仓库中。 | 不应用 Companion 开发来代替本项研究。 |

## 按版本看“能否在没有 Companion 的情况下谈有限闭环”

这是研究判断，前提是随后的实机验证通过。

**Ignition 8.3.9 + Artek（固定模块版本）：**

- 有限闭环（列出项目、读写已文档化的项目资源、改 View、改 Gateway 配置、读 Tag 值与配置、写 Tag **值**、只读数据库若开启、浏览器预览）在手册层面是**可讨论的**，不先做 Companion。
- 明显缺口：实时推送；手册中未见的 Tag/UDT 创建；Designer 级用户身份 API。
- 必须实机确认：写入后重载、继承拒绝、冲突、secret 掩码、部署超时语义。

**Ignition 2027.2.0-beta1 + Catalyst：**

- 目前只能确定：存在可配置的 MCP Server、`ignition` 内置分组、项目自定义工具，以及截图中的 Tag 读取类显示名。
- 项目写入、Tag 创建、配置写入、数据库浏览是否能经内置 MCP 完成，**未证实**。
- 因此 2027 路径在拿到 `tools/list` 和 CAT-06 之前，不应假设可以无 Companion、无自定义工具地替代 Designer。自定义工具或已证实的 OpenAPI 路由是比立刻写 Companion 更靠前的备选。

## 与需求相关、但不要误用的 Artek 工具

- `deploy_apply` 有失败回滚说明，但不校验脚本/JSON 内容；超时或不完整结果不能当成已回滚失败。
- `tag_write` 只写值。
- `get_session_details` 明确不返回 token 或原始 IdP 属性。
- `api_call` 的 authority 是配置的 Gateway API key，并且 GET 也被当作 mutating 管控；不等于当前登录用户。
