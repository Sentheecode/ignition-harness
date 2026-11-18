# 研究用薄适配层

2026-11-18（Asia/Singapore）。依据未合并 [PR #3](https://github.com/Sentheecode/ignition-harness/pull/3)，固定 tip `e0e583bcc18b989bd2ba1edb6f771f00eb5df570`。本分支从 main 新建，不合并或修改 PR #1/#2/#3，也不改历史调查文档。

## 实现范围与计划

沿用 Python 标准库，提供研究用库和一个手动的 `discover` / `plan` / `execute` 命令。没有产品 UI、后台服务或 Companion。命令不会在缺少 `--isolated-test-gateway` 时打开 socket，也不会把 header 值写到输出里。

- [x] 先以本地临时 HTTP server 写测试：实际 REST 请求形状、MCP 分页/会话、认证隔离、失败、禁用能力、ZIP 未知文件保留。
- [x] 实现仅接受显式隔离 loopback 目标的传输；拒绝生产端口 8088/8043/8060（含前导零写法）、用户信息、点路径、重定向与隐式代理。所有凭据由调用方提供，库不登录、创建 key、保存凭据或推测头名。
- [x] 公共 REST：读取目标 OpenAPI、项目创建、原生 ZIP 导出/显式覆盖导入；预览地址只生成，不打开浏览器、不证明预览已登录。
- [x] Tag 分版本：8.3.9 仅配置 import/export；Beta 提供 configuration 与运行值 read/write，不把配置导入称为运行值写入。
- [x] Catalyst：显式提供目标 endpoint，initialize、分页 tools/list 和已发现的 diagnostics/realtime/query/providers；8.3.9 MCP 保持 blocked，不提供假 Artek 客户端。
- [x] 工程、Gateway Web、MCP、Perspective 四种身份分别记录；实时订阅另列不支持。HTTP API 成功不证明工程身份，MCP realtime 是快照而非订阅。
- [x] 对照 PR #3 固定 tip 复核请求形状，补本地协议测试。结果只更新本 PR，不合并。

## 不承诺

项目 ZIP 覆盖不具备本轮已证实的资源级原子冲突合同；只允许调用方明确标记的自有、可丢弃测试项目。导入成功不等于 View 语义正确或运行时已经刷新。库不自动重试写入、自动恢复、重启 Gateway 或跨身份刷新 token。

PR #3 的 Beta 数据库预览出现 ERROR，因此不新增数据库 inspector 或声称 Beta DB 已通过。未找到官方外部 Designer 登录/续期 API；工程身份保留 unavailable。仅对文件数据做纯内存 View 修改，不提取或改动任何 Gateway 安装目录。

本轮测试只使用测试自行创建的临时 loopback HTTP server，不接触 Mac 的生产 `/usr/local/ignition`、8088，或任何已有 Gateway。公开实机证据是适配合同的来源，不冒充新代码已在 Mac Gateway 上复测。

## 文件与证据来源

库入口为 [research/ignition_adapter](../../research/ignition_adapter/__init__.py)，直接从仓库根目录导入，无新增运行依赖。测试为 [tests/test_research_adapter.py](../../tests/test_research_adapter.py)。

| 接口组 | 已核验合同 | 来源 |
|---|---|---|
| REST 发现 | `GET /openapi.json`；只使用该目标已发现的 operation | [Mac 认证/OpenAPI](https://github.com/Sentheecode/ignition-harness/blob/e0e583bcc18b989bd2ba1edb6f771f00eb5df570/docs/mac-isolated-gateway-2026-11-18.md) |
| 项目 | `POST /data/api/v1/projects`，正文只带证据里记下的 `name`；`GET /data/api/v1/projects/export/{name}`；`POST /data/api/v1/projects/import/{name}?overwrite=true`，ZIP 原始字节 | [独立 View 基线/修改/恢复](https://github.com/Sentheecode/ignition-harness/blob/e0e583bcc18b989bd2ba1edb6f771f00eb5df570/docs/evidence/mac-mini-isolated/view-write-preview-restore-2027-beta1.json)与该 PR 的 8.3.9 报告 |
| 8.3.9 Tag 配置 | 创建：`POST /data/api/v1/tags/import?provider=default&type=json&collisionPolicy=Abort`。更新再加 `&path=`。正文是调用方的 JSON 文件原始字节，`Content-Type: application/octet-stream`。读回：`GET /data/api/v1/tags/export?provider=&type=json&path=` | [8.3.9 逐步记录](https://github.com/Sentheecode/ignition-harness/blob/e0e583bcc18b989bd2ba1edb6f771f00eb5df570/docs/evidence/mac-mini-isolated/8.3.9-view-write-preview-restore.json) |
| Beta Tag | `tags` 与 `tagPaths` 是 string 数组；`values` 是数组，元素不收紧。配置正文只在调用方给出已列出属性时检查官方类型 | 字段名来自 Linux 临时摘录，SHA-256 `d7461e7bc941eebac42f75c2992968dd03b26fce4c505aad4e72612af696e4e0`，提交 `f44dc247811f4a50e6399196f6df8073e519342e`。类型来自 Mac 官方隔离 OpenAPI `openapi-2027.raw.json`，SHA-256 `b2bfc2d59854d48f313e33dc22f7302e8647f2a3be1cf6d0a42cd1d73d8c0ec4`，17223504 字节，mtime 2026-11-18 10:59:17 Asia/Singapore。17MB 原文件不入库 |
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
a.rest.create_project(allow_gateway_write=True)  # {"name": owned_project}，无其他字段
baseline_zip = a.rest.export_project()
preview_url = a.preview_url()  # 不发 HTTP，不判定 Perspective 身份或画面就绪
```

目标强制为 loopback、显式端口、指定版本和隔离声明。`8088`、`8043`、`8060` 按解析后的端口号拒绝，所以 `08088` 同样拒绝。用户信息、`@` 混淆和百分号编码的 host 也拒绝。构造实例不连接网络；网络只在显式调用方法时发生。这是研究误用防护，不是自动识别任意生产 Gateway 的机制。HTTP 不使用环境代理，301/302/303/307/308 在读取 Location 之前失败，单个响应和请求上限 32 MiB，默认 15 秒 socket 操作超时；不持久化 session，不自动重试。MCP 路径里的 `.`、`..` 和 `%` 编码会被拒绝。服务器返回的 session 值若含空格或控制字符，不会被存下来或写进后续请求，异常文本也不包含该值。

REST 与 MCP 的 header 字典分别复制、分别使用，没有默认的认证头或自动生成 token。PR #3 还明确记录：一枚可初始化 MCP 的 key 对 REST/OpenAPI 返回 403。因此不能把 MCP READY 当作 REST 授权，亦不能将失败归因为所有登录已过期。Web session cookie/CSRF 由真实浏览器流程提供，本库没有登录或续期功能。

### 项目 View 与恢复

`patch_existing_view(baseline_zip, existing_view_json_path, view_dict)` 只在内存中替换**已经存在**的 `view.json`，保留其他文件内容、原生 global-props、资源描述和 ZIP 条目元数据；不创建猜测的资源描述，不解压到磁盘，不验证第三方组件语义。

```python
from research.ignition_adapter import ProjectConflict, changed_project_paths, patch_existing_view

changed_zip = patch_existing_view(baseline_zip, verified_existing_path, edited_view)
a.rest.import_project(changed_zip, expected_current=baseline_zip, allow_overwrite=True, disposable_project=True)
changed_readback = a.rest.export_project()
changes = changed_project_paths(changed_zip, changed_readback)
if changes:
    raise ProjectConflict(changes)  # 意外变化需人工检查，停止恢复
# 调用方在真实 Perspective 中验证实际生效内容；本库不制造浏览器证据。
# 确认服务器仍是本实验状态后，显式恢复；不存在自动回滚或原子 compare-and-swap。
a.rest.import_project(baseline_zip, expected_current=changed_readback, allow_overwrite=True, disposable_project=True)
restored_readback = a.rest.export_project()
changes = changed_project_paths(baseline_zip, restored_readback)
if changes:
    raise ProjectConflict(changes)
```

每次导入前，适配层会重新导出项目，并按文件路径和解压后的字节比较。只含目录的 ZIP 条目（`ZipInfo.is_dir()`，或以 `/` 结尾且没有文件内容）不参与比较，压缩方式和条目顺序也不参与比较。文件新增、删除或内容变化会抛出 `ProjectConflict`，路径在 `.paths` 里；这一次调用只有导出 GET，没有导入 POST。`allow_overwrite` 和 `disposable_project` 仍然都要显式为真。比较和随后的导入是两次独立请求，中间仍有并发窗口。不自动重试，也不自动回滚。

通过 CLI 执行 `project.importZip` 时，参数 JSON 里用 `zip_path` 指向待导入文件，用 `expected_path` 指向保存的预期归档，并显式设置 `allow_overwrite` 和 `disposable_project` 为 true。冲突时 CLI 以退出码 2 返回 `project_contents_changed`。OpenAPI 里没有项目导出路径时，`discover` 把 `project.importZip` 标成 absent。

上述是有副作用的方法调用示意，不是在本轮执行的操作。只对调用方确认自有、可丢弃且独占编辑的隔离项目使用。不要在 `finally` 中无条件覆盖未知并发改动；超时先读回判断，不自动重试。归档覆盖可能影响整个项目，普通 hash/readback 不能消除并发窗口。恢复成功还需要调用方验证内容与真实预览，不能只根据 import 200 或字节长度判断。尾部带 `/` 的目录条目是合法打包，校验归档时会保留它们。

### Tag 分版本

- 8.3.9：`import_tag_configuration(provider, document_bytes, path=None, collision_policy='Abort'|'MergeOverwrite', allow_gateway_write=True)`。`path=None` 对应记录里的根上 Abort 创建，不附加 `path` 查询；传入文件夹时才附加记录中的 `&path=`。`document_bytes` 原样作为 `application/octet-stream` 发送，不重新 `json.dumps`。`export_tag_configuration(provider, path)` 读取配置。导入 Memory Tag value 可能改变默认值，这是配置导入，不是通用运行值写入 API。`read_values`、`write_values`、`configure_tags` 和 MCP 在 8.3.9 上拒绝，且不发请求。
- Beta：`read_values(document)` 和 `write_values(document, expected_count=..., allow_gateway_write=True)` 在 `plan` 和真正发请求之前检查官方类型。`tags` 和 `tagPaths` 必须是 string 数组；`values` 必须是数组，元素可以是任意 JSON 值，包括 `null`。NaN 和 Infinity 按官方说明写成字符串，库不把它们收成单一 item schema。字段名以外的键仍然拒绝。`{"paths": ...}` 或 `[{"path", "value"}]` 不会被改写，类型不符也不会被改写，检查失败时不发这次 Tag HTTP 请求。`read_values` 仍是 GET 加 JSON 正文。HTTP 200 只有在 `results` 非空、长度等于请求 `tags`、且每一项都是对象时才算读取成功。`value`、`quality`、`timestamp` 都不是必填，缺 `value` 仍然成功。出现 `quality` 时它必须是对象；出现 `quality.code` 时它必须是 JSON number，布尔值不算；出现 `quality.diagnosticMessage` 或 `timestamp` 时它们必须是字符串。读成功不要求 `quality.code == 192`，官方形状的非 Good quality 仍是成功读取，响应也不会被改写。若 `tagPaths` 和 `values` 都是数组且长度不同，在 POST 之前失败。`expected_count` 仍由调用方显式传入，并且在 `plan` 和 POST 之前必须等于 `len(tagPaths)`。HTTP 200 的 `results` 必须是对象数组，长度等于请求 `tagPaths`，每一项顶层 `code` 必须是 JSON number 且等于 192（`192.0` 可以，布尔值不行）。缺少 `diagnosticMessage` 不影响官方 Good 写入。嵌套 `quality.code` 不是写入成功。读接口里的 `quality.code` 不能当成写入成功。8.3.9 的 import/export 不会被拿来当作 Beta 运行值写入。
- Beta 配置：`configure_tags(document, allow_gateway_write=True)` 在文档是对象时，只检查已经出现的 `provider`、`path`、`collisionPolicy`（string）和 `tags`（object）。官方 request schema 没有 `type`、`required` 或 `additionalProperties`，所以缺字段和未列出的字段都保留。描述文字里的 collision policy 取值不是 schema enum。

字段名来自一台临时 Linux `2027.2.0-beta1` 隔离副本的已认证 OpenAPI，SHA-256 `d7461e7bc941eebac42f75c2992968dd03b26fce4c505aad4e72612af696e4e0`，提交 `f44dc247811f4a50e6399196f6df8073e519342e`。类型来自 Mac 上已保存的官方隔离 Gateway OpenAPI，文件 `openapi-2027.raw.json`，17223504 字节，SHA-256 `b2bfc2d59854d48f313e33dc22f7302e8647f2a3be1cf6d0a42cd1d73d8c0ec4`，mtime 2026-11-18 10:59:17 Asia/Singapore。那份 17MB 原文件不入库。库内副本是 [beta1-tag-openapi-fields.json](../../research/ignition_adapter/beta1-tag-openapi-fields.json)。这不是新的实机 Tag 写入。
- Tag 属于 Gateway/Provider 范围，项目归档覆盖确认不授权 Tag 操作，Tag 变更需要独立的显式写入标记。数据库 inspector、UDT 语义编辑和实时订阅未实现。

手动命令不读取 `/usr/local/ignition`，也不打印 header：

```bash
python -m research.ignition_adapter discover --version 8.3.9
python -m research.ignition_adapter plan \
  --operation tag.importConfiguration --version 8.3.9 --project HarnessLab \
  --args-file /path/outside/repo/import-args.json
python -m research.ignition_adapter execute --isolated-test-gateway \
  --operation tag.exportConfiguration --version 8.3.9 --project HarnessLab \
  --base-url "$LAB_GATEWAY_ORIGIN" \
  --headers-file /path/outside/repo/headers.json \
  --args-file /path/outside/repo/export-args.json
```

`discover` 只看本地版本策略和可选的 OpenAPI 文件，不因为版本字符串就宣布路由可用。它按操作报告文档策略：Beta 的 `tag.readValues` 和 `tag.writeValues` 对照 `beta1-tag-openapi-fields.json`，Beta 的 `tag.configure` 仍是调用方文档，8.3.9 的运行值读写是 `blocked_by_version`。`plan` 不打开 socket。`execute` 在标志缺失时直接拒绝。标准输出会把 header 值和 session 值替换成 `[redacted]`，并且不回显整份 OpenAPI。

### Catalyst 与状态

```python
a.mcp.initialize()
tools = a.mcp.list_tools()     # 完整分页后才建立可调用清单
result = a.mcp.realtime(paths) # 一次快照，不是订阅
# 另外三项：providers()、diagnostics(path)、query(path, quality=..., max_results=..., continuation_point=...)
```

调用参数来自固定 schema，query 的本地保守结果上限是 500；调用原始结果不改造为猜测的统一数据格式。`query` continuationPoint 与 tools/list cursor 是两种游标，调用方自行传入前者；库不将它们混用。

MCP session ID 只存在于客户端内存，而且只在对应的 HTTP 200 正文通过 JSON/RPC 检查之后才会保存。正文是残缺 JSON、id 类型不对、同时带 `result` 和 `error`，或含 `NaN`/`Infinity` 时，不采用随该响应到来的 `Mcp-Session-Id`，并清除已有 session、catalog 和 READY；下一次调用必须显式重新 initialize。格式正确的 JSON-RPC `error`（没有 `result`）仍只表示这一次调用失败，不把通道打成未初始化。`notifications/initialized` 不要求成功结果；空正文可以进入 READY，带 `error` 的正文则不能。session 值只接受最长 200 的可见 ASCII，拒绝 CR/LF、空格、引号和反斜杠；拒绝时异常文本不包含该值。这不表示已经在某个 HTTP 栈上复现出第二枚注入头。已建立 session 后 HTTP 404 会清除 session/catalog 并进入 EXPIRED；初始化 URL 首次 404 是 FAILED，不伪装成过期。401/403 为该 MCP 通道 DENIED。恢复必须显式重新 initialize、重新 list_tools；不会自动重放工具调用。没有额外 SSE 订阅、listChanged 持续监听或刷新工程身份的行为。项目 ZIP 在导入前检查条目名：拒绝控制字符（含被 `ZipInfo.filename` 截断后仍留在 `orig_filename` 里的 NUL）、盘符路径、反斜杠和 `..`。库仍不解压归档。

| 状态/能力 | 本库行为 |
|---|---|
| engineering | UNAVAILABLE；没有官方外部 Designer API，不实现登录/续期 |
| gateway_web | UNKNOWN；不从某个 API 响应推断浏览器身份有效 |
| mcp | 本客户端显式初始化/错误结果独立更新；8.3.9 为 BLOCKED |
| perspective | UNKNOWN；返回 URL 不等于认证或运行预览通过 |
| realtime_subscription | false；MCP realtime 为单次读取，不推断订阅在线 |

## 测试与本轮交付边界

`python3 -m unittest discover -v` 只连接测试自己创建的随机 loopback 端口；测试数据明确为 fixture。测试核对 8.3.9 导入查询串和原始字节、Beta 文档不被改写、项目创建正文、MCP initialize / `notifications/initialized` / `tools/list` 的请求，以及重定向、代理环境变量、点路径、坏 session 和 CLI 脱敏。结果是**新库的本地协议回归**，不是新一轮 Mac Gateway 实测。

只引用 PR #3 的公开证据，不复制该 PR 的历史报告，不合并它或另外两份 PR。库没有生产目标配置、UI、Companion、第三方模块二进制、凭据文件或实际项目 ZIP。

### 本轮验证结果

`python3 -m unittest discover -v tests -t .` 为 48 项通过，26.929 秒。Beta Tag 读写作在发请求前按库内摘录检查顶层字段和官方 JSON 类型；读取成功还要求 `results` 与请求 `tags` 等长且每项都是对象。写入在 POST 前要求 `expected_count` 等于 `tagPaths` 长度，成功只认等长且顶层 `code` 为 192 的 Quality Code。配置导入仍走 8.3.9 的原始字节和查询串。项目覆盖在导入前按文件内容比较；只含目录的 ZIP 条目不算内容变化。无效 MCP 成功响应不再留下 READY 或新 session。ZIP 条目名拒绝控制字符和盘符路径，但保留以 `/` 结尾的目录条目。MCP schema 的来源哈希仍对应固定提交 `e0e583bcc18b989bd2ba1edb6f771f00eb5df570`。此库为同步、单调用方研究接口，不支持多线程共享同一实例。没有运行任何既有 Gateway 的探测、写入或登录。这些测试仍不是 Mac 实机证据。
