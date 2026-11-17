# Ignition Harness

面向 Inductive Automation Ignition 的 AI 工程工作台研究项目。

目标：提供类似 DeepSeek Harness 的桌面工程工作台。左侧 Projects 管理项目与持久登录，直接操作 Gateway 中的 Tag、画面、脚本与配置，并提供实时点位、数据库浏览和内置 Perspective 预览。

**状态：调研阶段。尚无可运行产品，也未完成 Gateway 实机兼容验证。**

## 目标版本

- Ignition 8.3.9 及后续 8.3.x：Artek-MCP 适配路径。
- Ignition 2027 Beta：Catalyst Agent MCP Server 适配路径；按具体 build 验证。
- 不承诺自动支持未来所有版本，也不假定两种 MCP 服务具有相同工具。

## 文档

优先阅读本轮深入调查、2026-11-17 补充与用户确认范围；早期文档保留研究过程，以最新调查及本补充为准。

- [用户确认的完整产品范围](docs/product-requirements.md)
- [深入技术调查：Beta SDK、实际工具、登录与实时链路](docs/technical-investigation.md)
- [Beta1 SDK 可复核证据](docs/evidence/2027.2.0-beta1-sdk.json)
- [Configure Primitives 截图笔记、Docker 标签元数据、Artek 手册工具摘录与 MCP 采集程序](docs/evidence/)
- [2026-11-17 补充：四个阻塞项的公开证据与验证程序](docs/research-supplement-2026-11-17.md)
- [需求能力缺口矩阵](docs/capability-gap-matrix.md)

- [调研结论与来源](docs/research.md)
- [Catalyst 专项调研](docs/catalyst-research.md)
- [建议架构与方案比较](docs/architecture-proposal.md)
- [首轮验证与 MVP 路线](docs/validation-roadmap.md)

2026-11-17 补充调查（仍无实机 Gateway）进一步收窄了四个阻塞项：

- 公开手册和官方截图仍不能代替 2027.2.0-beta1 的 MCP `tools/list`；截图可见的内置项是 `ignition/tags` 下的读取/查询/诊断显示名。采集程序见文档。
- 未找到可供第三方工作台稳定调用的官方 Designer 登录/续期 API。机器访问应使用文档化的 API Key；用户登录与 Perspective 预览走各自的浏览器/IdP 会话，四种状态不可合并。
- Gateway Companion 现在不必做。8.3 的有限资源/配置写入应先验证 Artek 与官方配置 REST。实时 Tag 订阅，以及在 OpenAPI/自定义工具仍无法覆盖时的 Tag/UDT 创建，可能稍后才需要模块。
- 写入、刷新、冲突和预览仍必须在隔离的 8.3.9 与 2027.2.0-beta1 Gateway 上验证。官方镜像标签 `inductiveautomation/ignition:2027.2.0-beta1`（amd64/arm64）与 `8.3.9` 已在 Docker Hub 核验标签元数据，但尚未拉取或运行。2027 Beta 不得用于生产；现有许可证与该 Beta 不兼容。

在得到脱敏的实机工具清单，并完成至少一次真实 View 写入与预览闭环之前，不开始堆砌产品页面。

初期建议复用真实 Perspective runtime，通过工作台集中预览；不自行重写其渲染、绑定和脚本运行时。

项目为独立研究，与 Inductive Automation、Artek 或 DeepSeek 无隶属关系。第三方模块不随本仓库分发。开源许可待项目所有者决定。
