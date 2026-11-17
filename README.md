# Ignition Harness

面向 Inductive Automation Ignition 的 AI 工程工作台研究项目。

目标：提供类似 DeepSeek Harness 的桌面工程工作台。左侧 Projects 管理项目与持久登录，直接操作 Gateway 中的 Tag、画面、脚本与配置，并提供实时点位、数据库浏览和内置 Perspective 预览。

**状态：已完成一轮隔离 2027.2.0-beta1 Gateway 运行验证；桌面产品尚未实现，8.3.9 + Artek 仍待运行验证。**

## 目标版本

- Ignition 8.3.9 及后续 8.3.x：Artek-MCP 适配路径。
- Ignition 2027 Beta：Catalyst Agent MCP Server 适配路径；按具体 build 验证。
- 不承诺自动支持未来所有版本，也不假定两种 MCP 服务具有相同工具。

## 文档

优先阅读本轮深入调查与用户确认范围；早期文档保留研究过程，以最新调查的修订为准。

- [2027.2.0-beta1 实际 Gateway 验证结果](docs/runtime-validation-2027-beta1.md)
- [用户确认的完整产品范围](docs/product-requirements.md)
- [深入技术调查：Beta SDK、实际工具、登录与实时链路](docs/technical-investigation.md)
- [Beta1 SDK 可复核证据](docs/evidence/2027.2.0-beta1-sdk.json)

- [调研结论与来源](docs/research.md)
- [Catalyst 专项调研](docs/catalyst-research.md)
- [建议架构与方案比较](docs/architecture-proposal.md)
- [首轮验证与 MVP 路线](docs/validation-roadmap.md)

初期建议复用真实 Perspective runtime，通过工作台集中预览；不自行重写其渲染、绑定和脚本运行时。

项目为独立研究，与 Inductive Automation、Artek 或 DeepSeek 无隶属关系。第三方模块不随本仓库分发。开源许可待项目所有者决定。
