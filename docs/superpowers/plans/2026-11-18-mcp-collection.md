# 脱敏 MCP 采集与隔离验证 Implementation Plan

> **For agentic workers:** Execute the two tasks below in this session. No product UI, adapter, third-party binary, or existing Gateway operation is in scope.

**Goal:** 交付用户明确要求的脱敏只读采集器和 8.3.9 / 2027.2.0-beta1 隔离验证清单，并推送远程分支。

**Architecture:** 新增 Python 标准库 CLI，不修改旧探针或历史调查。endpoint 与认证头均由操作者从隔离环境取得；仅执行 initialize、initialized、分页 tools/list，选配独立认证的 OpenAPI GET。结构化输出脱敏且保留失败/未完成状态。

**Tech Stack:** Python 3、urllib、unittest、本地临时 HTTP 协议测试服务。

**Spec:** 用户 2026-11-18 本会话要求；[PR #1](https://github.com/Sentheecode/ignition-harness/pull/1)，head `7d653e7dcd88f3d0f61b621f6a0ee3b97e875167`。PR 与 main 的历史陈述分别保留，本轮不合并或重写。

## Global Constraints

- 不使用或改动任何现有的生产性质 Gateway；本轮运行测试只连接测试进程自己创建的临时 HTTP server。
- 不编造工具名、endpoint 或认证头，不提供 Designer 登录客户端。
- 不改写历史调查文档、不添加第三方模块二进制、不新增产品 UI 或薄适配层。
- 单次真实 View 写入 + 预览 + 恢复闭环未经核验，不开启适配层工作。

## Review Focus

- 跨页 JSON/SSE 响应、空/重复 cursor 与服务端失败必须可区分，不输出伪完整清单。
- 凭据、cookie/session/cursor、内部主机与自定义敏感字面量不能进入 stdout、stderr 或证据。
- 携带凭据的重定向请求必须拒绝，不把认证发送到别的 URL。
- 可选 OpenAPI 必须同 origin、独立输入认证，失败与 MCP 完成状态分别记录。
- 输出不得覆盖输入或旧证据；网络错误和权限拒绝不自动变更服务端配置。

## Task 1 — 采集器

Files: `research/collect_mcp_evidence.py`, `tests/test_collect_mcp_evidence.py`, `tests/__init__.py`。

- [x] 先写并运行 CLI 集成测试，观察旧实现/缺失实现不能通过。
- [x] 实现初始化、通知、分页 JSON/SSE；只使用这三类 MCP method，不调用工具。
- [x] 实现输入验证、脱敏、分页/响应上限、无重定向、失败快照和可选 OpenAPI。
- [x] 运行整个 unittest suite；测试报告明确为本地协议 fixture。

## Task 2 — 清单与交付

Files: `research/MCP_COLLECTION.md`, `docs/validation/isolated-gateway-checklist-2026-11-18.md`。

- [x] 写运行命令、私有输入约定、脱敏边界、匿名/候选认证分别采集规则。
- [x] 写两版本身份/版本/OpenAPI/模块清单，View 基线、单次写入、真实预览、恢复及恢复后预览；冲突和刷新单独记录。
- [x] 验证文档链接、历史文档未改动、无二进制/凭据、完整测试通过。
- [ ] commit、push 新分支；保留 PR #1 未合并状态。

## 本轮验证记录

`python -m unittest discover -v`：18 项通过，只运行测试自行创建的临时 HTTP server，不是 Gateway 实测。独立代码审查发现并修复敏感容器脱敏与 OpenAPI 命名定义保留问题，回归测试覆盖。未操作任何既有 Gateway。
