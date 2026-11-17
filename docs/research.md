# 调研记录

调研日期：2026-11-17。下列是公开资料研究，不是安装测试报告。供应商能力声明仍需通过具体模块版本与 Gateway build 验证。

## 核心判断

技术上适合构建专用于 Ignition 的 agent harness，但应把“替代开发入口”和“重写 Ignition 平台”区分开。可以逐步统一需求描述、项目理解、资源修改、审查、部署及预览；尚无证据支持仅连接 MCP 就能完整替代 Designer 的所有工作区。

用户称“gateway designer”，本文理解为 Ignition Designer，并把 Gateway 管理界面作为另一类能力。Perspective 预览理解为工作台内呈现真实运行会话，而不是另造一套兼容 renderer；这两项理解待产品讨论确认。

## 版本与连接

| 路径 | 已有公开依据 | 尚未确认 |
|---|---|---|
| 8.3.9+ / Artek | 产品页声明支持 8.3.4+，可作为用户要求的 8.3.9 基线候选；Streamable HTTP | 逐版本安装、资源读写语义、编辑后加载行为 |
| 2027 Beta / Catalyst | 官方文档目前标注 2027.02 Beta；提供面向外部客户端的 MCP Server | 内置工具具体清单、项目编辑覆盖率、权限映射与 build 差异 |

### Artek-MCP

产品页列出 v1.1.0、95 个预置工具及 `/data/artek-mcp/mcp` 入口，默认只读。支持项目资源、标签和诊断等范围，并允许受控写入。产品页还提到 Artek-Designer，说明另有依赖打开 Designer 的编辑路线，需单独研究，不能把它的能力归给 Gateway MCP。

其免费模块不是已确认的开源 SDK；不要把“免费”理解为允许修改或再分发。具体工具 schema、资源写入后是否重载及并发覆盖行为，需要获取实际 `tools/list` 和手册后再建立映射。[S1]

### Catalyst

应连接 **Services > Catalyst > MCP Servers** 创建的服务；**MCP Connections** 是 Ignition 向外部服务发起连接，方向不同。官方采用 Streamable HTTP；服务器可暴露自定义工具和 `ignition` 分组的内置工具，不能沿用第三方页面“官方没有预置工具”的比较作为当前结论。

官方文档还列出 Catalyst Core、模型提供者配置前提。外部 Harness 是否仍需这些完整配置，按对应 Beta 实机确认；使用 Gateway 提供的 Copy Endpoint URL，勿猜测路径。[S2]

## Designer 替代范围

| 功能 | 建议策略 | 当前证据等级 |
|---|---|---|
| 项目/资源检索 | MCP 发现后映射为统一读取能力 | 文档支持方向，未实测 |
| Perspective View / Style / 脚本修改 | 本地工作副本 + 差异 + 服务端资源写入 | 资源类型和写入链路待验证 |
| 标签、UDT、Named Query | 分类型适配，不合并为任意脚本执行 | 覆盖范围待验证 |
| 图形拖拽、复杂绑定编辑器 | 后续独立产品能力 | MCP 不自动提供这些 UI |
| Vision、Reporting、第三方设计器 | 暂不纳入首个 MVP | 不宣称完整替代 |
| Gateway 模块/安全管理 | 独立于项目编辑规划 | 不作为首轮写入范围 |

## Perspective 预览

Perspective 是运行于 Ignition 架构中的浏览器应用，真实行为依赖 Gateway、会话、标签、权限和脚本。[S3] 据此建议：在开发 Gateway 中部署工作副本，再在工作台内打开真实会话。单纯渲染 View JSON 只能做近似静态草图，不能作为功能验收。

iframe 是否可用须验证 CSP、frame-ancestors、Cookie、IdP 跳转和 WebSocket；如果受限，评估独立 webContents 或由工作台管理的浏览器窗口，不绕过服务端安全策略。预览运行的是已部署资源，未保存修改不能假称已生效。

## DeepSeek Harness 参考价值

官方项目采用插件架构，适合参考模型接入、agent loop、工具注册和会话 UI 的分离方式。[S4] 三种可行方向是：做 DSH 插件、派生整套 DSH 产品、或独立工作台复用成熟协议库。当前建议独立领域内核，先验证 DSH 插件接入成本；不要未经代码审查就决定 fork。

## 来源

- [S1 Artek-MCP 产品页](https://artekis.io/community/artek-mcp) — 第三方供应商声明，含版本、传输、默认权限和许可证入口。
- [S2 Catalyst Agent 官方文档](https://docs.inductiveautomation.com/docs/2027/ignition-modules/catalyst/catalyst-agent) — 当前 2027.02 Beta，连接方向、工具暴露、模块依赖。
- [S3 Perspective 官方介绍](https://docs.inductiveautomation.com/docs/8.3/ignition-modules/perspective) — 浏览器架构与运行环境。
- [S4 DeepSeek Harness 源仓库](https://github.com/deepseek-ai/deepseek-harness) — 插件架构参考，复用前检查固定 commit 与许可。
- [S5 8.3.9 发布说明](https://links.inductiveautomation.com/downloads/releasenotes/8.3.9) — 目标版本依据，不等于第三方模块兼容认证。
- [S6 8.3 → 2027 升级指南](https://docs.inductiveautomation.com/docs/2027/getting-started/installing-and-upgrading/ignition-8-upgrade-guide/83to2027-upgrade-guide) — 第三方兼容性及迁移注意事项。
