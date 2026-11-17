# Ignition Harness

面向 Inductive Automation Ignition 的 AI 工程工作台研究项目。

目标：用自然语言、资源编辑、差异审查与真实运行预览，逐步承接 Ignition Designer 和独立 Perspective 预览窗口的日常工作。

**状态：调研阶段。尚无可运行产品，也未完成 Gateway 实机兼容验证。**

## 目标版本

- Ignition 8.3.9 及后续 8.3.x：Artek-MCP 适配路径。
- Ignition 2027 Beta：Catalyst Agent MCP Server 适配路径；按具体 build 验证。
- 不承诺自动支持未来所有版本，也不假定两种 MCP 服务具有相同工具。

## 文档

- [调研结论与来源](docs/research.md)
- [Catalyst 专项调研](docs/catalyst-research.md)
- [建议架构与方案比较](docs/architecture-proposal.md)
- [首轮验证与 MVP 路线](docs/validation-roadmap.md)

初期建议复用真实 Perspective runtime，通过工作台集中预览；不自行重写其渲染、绑定和脚本运行时。

项目为独立研究，与 Inductive Automation、Artek 或 DeepSeek 无隶属关系。第三方模块不随本仓库分发。开源许可待项目所有者决定。
