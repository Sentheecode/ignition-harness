# 研究用薄适配层

2026-11-18（Asia/Shanghai）。依据未合并 [PR #3](https://github.com/Sentheecode/ignition-harness/pull/3)，固定 tip `e0e583bcc18b989bd2ba1edb6f771f00eb5df570`。本分支从 main 新建，不合并或修改 PR #1/#2/#3，也不改历史调查文档。

## 实现范围与计划

沿用 Python 标准库，提供研究用库，不提供产品 UI、后台服务、Companion 或自动执行的实验 CLI。

- [x] 先以本地临时 HTTP server 写测试：实际 REST 请求形状、MCP 分页/会话、认证隔离、失败、禁用能力、ZIP 未知文件保留。
- [x] 实现仅接受显式隔离 loopback 目标的传输；拒绝生产端口 8088、重定向与隐式代理。所有凭据由调用方提供，库不登录、创建 key、保存凭据或推测头名。
- [x] 公共 REST：读取目标 OpenAPI、项目原生 ZIP 导出/显式覆盖导入；预览地址只生成，不打开浏览器、不证明预览已登录。
- [x] Tag 分版本：8.3.9 仅配置 import/export；Beta 提供 configuration 与运行值 read/write，不把配置导入称为运行值写入。
- [x] Catalyst：显式提供目标 endpoint，initialize、分页 tools/list 和已发现的 diagnostics/realtime/query/providers；8.3.9 MCP 保持 blocked，不提供假 Artek 客户端。
- [x] 工程、Gateway Web、MCP、Perspective 四种身份分别记录；实时订阅另列不支持。HTTP API 成功不证明工程身份，MCP realtime 是快照而非订阅。
- [ ] 完成全套离线/本地协议测试和独立审查，新分支推远程并开 PR，不合并。

## 不承诺

项目 ZIP 覆盖不具备本轮已证实的资源级原子冲突合同；只允许调用方明确标记的自有、可丢弃测试项目。导入成功不等于 View 语义正确或运行时已经刷新。库不自动重试写入、自动恢复、重启 Gateway 或跨身份刷新 token。

PR #3 的 Beta 数据库预览出现 ERROR，因此不新增数据库 inspector 或声称 Beta DB 已通过。未找到官方外部 Designer 登录/续期 API；工程身份保留 unavailable。仅对文件数据做纯内存 View 修改，不提取或改动任何 Gateway 安装目录。

本轮测试只使用测试自行创建的临时 loopback HTTP server，不接触 Mac 的生产 `/usr/local/ignition`、8088，或任何已有 Gateway。公开实机证据是适配合同的来源，不冒充新代码已在 Mac Gateway 上复测。

## 文件与证据来源

库入口为 [research/ignition_adapter](../../research/ignition_adapter/__init__.py)，直接从仓库根目录导入，无新增运行依赖。测试为 [tests/test_research_adapter.py](../../tests/test_research_adapter.py)。

| 接口组 | 已核验合同 | 来源 |
|---|---|---|
| REST 发现 | `GET /openapi.json`；只使用该目标已发现的 operation | [Mac 认证/OpenAPI](https://github.com/Sentheecode/ignition-harness/blob/e0e583bcc18b989bd2ba1edb6f771f00eb5df570/docs/mac-isolated-gateway-2026-11-18.md) |
| 项目归档 | `GET /data/api/v1/projects/export/{name}`；`POST /data/api/v1/projects/import/{name}?overwrite=true`，ZIP 原始字节 | [独立 View 基线/修改/恢复](https://github.com/Sentheecode/ignition-harness/blob/e0e583bcc18b989bd2ba1edb6f771f00eb5df570/docs/evidence/mac-mini-isolated/view-write-preview-restore-2027-beta1.json)与该 PR 的 8.3.9 报告 |
| 8.3.9 Tag 配置 | `/data/api/v1/tags/import` 原始 JSON 文件字节；`/data/api/v1/tags/export` | [8.3.9 逐步记录](https://github.com/Sentheecode/ignition-harness/blob/e0e583bcc18b989bd2ba1edb6f771f00eb5df570/docs/evidence/mac-mini-isolated/8.3.9-view-write-preview-restore.json) |
| Beta Tag | `/data/api/v1/tags/configuration` POST；`/tags/read` GET **JSON body**；`/tags/write` POST | [Mac Beta 记录](https://github.com/Sentheecode/ignition-harness/blob/e0e583bcc18b989bd2ba1edb6f771f00eb5df570/docs/evidence/mac-mini-isolated/2027.2.0-beta1-view-write-preview-restore.json)、[已存在的请求结果](https://github.com/Sentheecode/ignition-harness/blob/547587fcd97f9885c56bce6102c7b6e6a5a86baa/docs/evidence/runtime-beta1/tag-runtime-results.json) |
| Catalyst | 显式传入从目标复制的 endpoint；协议 `2025-06-18`；四项工具的实际 inputSchema | [Mac 工具合同](https://github.com/Sentheecode/ignition-harness/blob/e0e583bcc18b989bd2ba1edb6f771f00eb5df570/docs/evidence/mac-mini-isolated/2027.2.0-beta1-mcp-tools.redacted.json) |
| Perspective | `/data/perspective/client/{project}` 地址生成 | 同一 Mac View 记录；不是 `/app/perspective/...` SPA 外壳 |

库中的 [catalyst_contract.json](../../research/ignition_adapter/catalyst_contract.json) 是固定证据中四份 inputSchema 的派生快照，记录原文件 SHA-256 与 commit，未带入 endpoint、token 或 session。工具发现结果会完整保留；调用只允许这四项，并要求对应的发现 schema 与快照一致。未来 build/schema 改变时拒绝调用，需补研究证据再更新；不凭同名工具放行。Mac 记录只做了工具发现；调用响应形状另有 main 已存在的 [Linux MCP 调用记录](https://github.com/Sentheecode/ignition-harness/blob/547587fcd97f9885c56bce6102c7b6e6a5a86baa/docs/evidence/runtime-beta1/mcp-call-results.json)。不把 Mac tools/list 描述为四项工具全部调用成功。

## 使用方式与约束

代码示意，**不是自动运行的实验**。URL、版本、项目、headers 均由调用方从其获准使用的隔离实例提供；不从历史记录选择目标或读取 `/usr/local/ignition`。HTTP/MCP 凭据放仓库外，通过私有输入读取。不要将返回的 OpenAPI、归档、Tag 结果或 schema 中的现场内容直接写日志或提交。

```python
from research.ignition_adapter import LabTarget, ResearchAdapter

# lab_base_url / lab_version / owned_project / rest_headers 来自调用方私有配置。
target = LabTarget(lab_base_url, lab_version, isolated_test_gateway=True)
a = ResearchAdapter(target, owned_project,
                    rest_headers=rest_headers,
                    mcp_endpoint=verified_catalyst_endpoint,  # 8.3.9 使用 None
                    mcp_headers=mcp_headers)                 # 不复用 Web cookie

a.rest.discover()              # 先读该目标 OpenAPI；不会登录或刷新凭据
baseline_zip = a.rest.export_project()
preview_url = a.preview_url()  # 不发 HTTP，不判定 Perspective 身份或画面就绪
```

目标强制为 loopback、显式端口、指定版本和隔离声明，拒绝 8088/8043/8060 等生产默认端口。构造实例不连接网络；网络只在显式调用方法时发生。这是研究误用防护，不是自动识别任意生产 Gateway 的机制。HTTP 不使用环境代理、不跟随重定向，单个响应和请求上限 32 MiB，默认 15 秒 socket 操作超时；不持久化 session，不自动重试。

REST 与 MCP 的 header 字典分别复制、分别使用，没有默认的认证头或自动生成 token。PR #3 还明确记录：一枚可初始化 MCP 的 key 对 REST/OpenAPI 返回 403。因此不能把 MCP READY 当作 REST 授权，亦不能将失败归因为所有登录已过期。Web session cookie/CSRF 由真实浏览器流程提供，本库没有登录或续期功能。

### 项目 View 与恢复

`patch_existing_view(baseline_zip, existing_view_json_path, view_dict)` 只在内存中替换**已经存在**的 `view.json`，保留其他文件内容、原生 global-props、资源描述和 ZIP 条目元数据；不创建猜测的资源描述，不解压到磁盘，不验证第三方组件语义。

```python
from research.ignition_adapter import patch_existing_view

changed_zip = patch_existing_view(baseline_zip, verified_existing_path, edited_view)
a.rest.import_project(changed_zip, allow_overwrite=True, disposable_project=True)
changed_readback = a.rest.export_project()
# 调用方在真实 Perspective 中验证实际生效内容；本库不制造浏览器证据。
# 确认服务器仍是本实验状态后，显式恢复；不存在自动回滚或原子 compare-and-swap。
a.rest.import_project(baseline_zip, allow_overwrite=True, disposable_project=True)
restored_readback = a.rest.export_project()
```

上述是有副作用的方法调用示意，不是在本轮执行的操作。只对调用方确认自有、可丢弃且独占编辑的隔离项目使用。不要在 `finally` 中无条件覆盖未知并发改动；超时先读回判断，不自动重试。归档覆盖可能影响整个项目，普通 hash/readback 不能消除并发窗口。恢复成功还需要调用方验证内容与真实预览，不能只根据 import 200 或字节长度判断。

### Tag 分版本

- 8.3.9：`import_tag_configuration(provider, path, document, collision_policy=..., allow_gateway_write=True)` 采用已验证的 Abort/MergeOverwrite 配置导入；`export_tag_configuration` 读取配置。导入 Memory Tag value 可能改变默认值，**不是**通用运行值写入 API。`write_values` 和 MCP 均拒绝，不尝试 fallback。
- Beta：`configure_tags(..., allow_gateway_write=True)` 处理配置；`read_values(paths)` 是 GET JSON body；`write_values(paths, values, allow_gateway_write=True)` 是独立值写入。检查逐项结果，仅把本轮已证实的质量码 192 当作全项 Good，其余结果失败返回，不自动再次写入。
- Tag 属于 Gateway/Provider 范围，项目归档覆盖确认不授权 Tag 操作，Tag 变更需要独立的显式写入标记。数据库 inspector、UDT 语义编辑和实时订阅未实现。

### Catalyst 与状态

```python
a.mcp.initialize()
tools = a.mcp.list_tools()     # 完整分页后才建立可调用清单
result = a.mcp.realtime(paths) # 一次快照，不是订阅
# 另外三项：providers()、diagnostics(path)、query(path, quality=..., max_results=..., continuation_point=...)
```

调用参数来自固定 schema，query 的本地保守结果上限是 500；调用原始结果不改造为猜测的统一数据格式。`query` continuationPoint 与 tools/list cursor 是两种游标，调用方自行传入前者；库不将它们混用。

MCP session ID 只存在于客户端内存。已建立 session 后 HTTP 404 会清除 session/catalog 并进入 EXPIRED；初始化 URL 首次 404 是 FAILED，不伪装成过期。401/403 为该 MCP 通道 DENIED。恢复必须显式重新 initialize、重新 list_tools；不会自动重放工具调用。没有额外 SSE 订阅、listChanged 持续监听或刷新工程身份的行为。

| 状态/能力 | 本库行为 |
|---|---|
| engineering | UNAVAILABLE；没有官方外部 Designer API，不实现登录/续期 |
| gateway_web | UNKNOWN；不从某个 API 响应推断浏览器身份有效 |
| mcp | 本客户端显式初始化/错误结果独立更新；8.3.9 为 BLOCKED |
| perspective | UNKNOWN；返回 URL 不等于认证或运行预览通过 |
| realtime_subscription | false；MCP realtime 为单次读取，不推断订阅在线 |

## 测试与本轮交付边界

`python -m unittest discover -v` 只连接测试自己创建的随机 loopback 端口；测试数据明确为 fixture。测试覆盖真实请求编码、JSON/SSE 分页、逐项失败、凭据隔离、版本拒绝、schema 变化、session 过期与归档保留。结果是**新库的本地协议回归**，不是新一轮 Mac Gateway 实测。

只引用 PR #3 的公开证据，不复制该 PR 的历史报告，不合并它或另外两份 PR。库没有生产目标配置、UI、Companion、第三方模块二进制、凭据文件或实际项目 ZIP。

### 本轮验证结果

21 项本地协议回归通过；独立代码审查发现的畸形 HTTP 状态行异常泄漏已修复并加入失败/通过回归。MCP schema 的来源哈希及所用 REST 路径已与 PR #3 固定提交复核。此库为同步、单调用方研究接口，不支持多线程共享同一实例。没有运行任何既有 Gateway 的探测、写入或登录。
