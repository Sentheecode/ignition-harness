# 薄 Gateway 适配器（2026-11-18）

这是研究笔记，不是桌面产品说明。适配器把已经在 Mac 隔离 Gateway 上核对过的领域操作，映射成调用方提供端点上的 HTTP 或 MCP 调用。它不包含产品界面、Electron 壳或 Companion 模块。

## 它做什么

库在 `ignition_harness/adapter/`。命令行：

```bash
python -m ignition_harness.adapter discover \
  --openapi-summary docs/evidence/mac-mini-isolated/2027.2.0-beta1-openapi.summary.json \
  --tools-file docs/evidence/mac-mini-isolated/2027.2.0-beta1-mcp-tools.redacted.json \
  --identity-file /path/outside/repo/identity.json

python -m ignition_harness.adapter plan \
  --operation tag.writeValues \
  --args-file /path/outside/repo/args.json \
  --openapi-summary docs/evidence/mac-mini-isolated/2027.2.0-beta1-openapi.summary.json \
  --identity-file /path/outside/repo/identity.json

python -m ignition_harness.adapter execute \
  --isolated-test-gateway \
  --operation tag.writeValues \
  --base-url "$LAB_GATEWAY_ORIGIN" \
  --headers-file /path/outside/repo/headers.json \
  --args-file /path/outside/repo/args.json \
  --openapi-summary docs/evidence/mac-mini-isolated/2027.2.0-beta1-openapi.summary.json \
  --identity-file /path/outside/repo/identity.json \
  --output /path/outside/repo/adapter-result.json
```

`identity.json` 只放版本、build 和模块 id。`headers.json` 是调用方已经拿到的头，值不会写进输出。`--output` 必须是新文件。没有 `--isolated-test-gateway` 时，`execute` 不会发起网络请求。

领域操作是 `gateway.discoverCapabilities`、`project.create`、`project.importZip`、`tag.configure`、`tag.readValues`、`tag.writeValues`、`tag.importConfiguration`、`tag.exportConfiguration`、`mcp.listTools`、`preview.clientUrl`。公开名字不是 wire 工具名。

## 能力从输入来，不从版本号来

能力表同时看调用方给出的 OpenAPI（路径摘要或带方法的文档）、模块 id，以及可选的已脱敏 `tools/list`。只给 `2027.2.0-beta1` 或 `8.3.9` 字符串，不会打开项目、Tag 或 MCP 功能。

Mac 隔离摘要里，2027.2.0-beta1 是 696 条路径、809 个操作；8.3.9 是 580 条路径、679 个操作。摘要只有路径名时，适配器只给已经核对过的方法填 HTTP method，不会假设每个路径都支持全部动词。

## 两边已经核对的合同

认证由调用方提供。适配器不登录、不续期、不创建 API token，也不保存 cookie 或 token。Mac 隔离环境里，REST 变更用的是 Web 会话 cookie 加 `X-CSRF-Token`；Catalyst MCP 不接受这套 Web 会话，用的是 `X-Ignition-API-Token`。这些只是证据里的头名，不是适配器自动加上的头。

共享：

- `project.create`：`POST /data/api/v1/projects`，JSON 只带 `name`。
- `project.importZip`：`POST /data/api/v1/projects/import/{name}?overwrite=true`，正文是 ZIP。合并夹具时保留原生 `project.json` 和 `global-props`，夹具不能替换它们。只核对过 `overwrite=true`。
- `preview.clientUrl`：活客户端是 `/data/perspective/client/{project}`。`/app/perspective/client/{project}` 只是 Gateway SPA 壳。导入后立刻 GET 活客户端可能短暂 404，适配器记录这一状态，不自动重试。

2027.2.0-beta1，且 OpenAPI 里真有对应路径时：

- `tag.configure`：`POST /data/api/v1/tags/configuration`。正文是调用方给出的 Tag 对象数组，每项必须有 `[provider]path`。
- `tag.writeValues`：`POST /data/api/v1/tags/write`。隔离 Linux 2027.2.0-beta1 的 OpenAPI 摘录要求正文是对象，必填 `tagPaths` 与 `values`（`f44dc24` 的 `docs/evidence/isolated-linux-same-tab/beta1-tag-openapi-fields.json`）。适配器在发送前用这份摘录检查正文。摘录没有字段内部 schema，因此两个数组按调用方的写入列表对齐。早先的 `[{path, value}]` 不符合该实例声明的合同。
- `tag.readValues`：`GET /data/api/v1/tags/read`，JSON 正文是对象，必填 `tags`。同样在发送前对照摘录检查。`{paths}` 不符合该合同。Mac 证据仍记录这是带 JSON 正文的 GET，以及读回的值和质量码 `192`。
- `mcp.listTools`：只在调用方给出 MCP 端点时执行 `initialize`、`notifications/initialized` 和分页 `tools/list`。不猜测 `/data/catalyst-agent/mcp-servers/{name}`。Mac 上实列的四个工具是 `diagnostics`、`realtime`、`query`、`providers`；适配器不补工具，也不在测试里对真 Gateway 执行工具。写入走上面的 REST，不发明 MCP 写工具。

8.3.9：

- `tag.importConfiguration`：`POST /data/api/v1/tags/import`，`Content-Type: application/octet-stream`。创建用 `provider=default&type=json&collisionPolicy=Abort`。更新用 `collisionPolicy=MergeOverwrite` 加 `path`。这是配置导入。Memory Tag 的 value 被导入后，现场值可以跟着变，但适配器仍把它标成配置导入，不是通用运行值写入 API。
- `tag.exportConfiguration`：`GET /data/api/v1/tags/export?provider=default&type=json&path=...`。这是配置读回，不是运行值读取。
- `tag.writeValues`、`tag.readValues`、`tag.configure` 在 8.3.9 上失败关闭，即使有人把 2027 的路径写进一份 OpenAPI 摘要。
- `mcp.listTools` 失败关闭。原因是这台隔离 8.3.9 没有安装 Artek-MCP，匿名 `/mcp` 为 404。适配器不发出 `tools/list`，也不编造工具。

## 安全边界

执行请求不跟随 301/302/303/307/308，也不使用环境代理。输出只保留头名和状态码，头值、MCP session、分页 cursor 会从保存结果里去掉。短于 4 个字符的字面量不做字符串替换。脱敏是尽力而为，发布前仍要人工看。

本地测试是进程内的 fixture HTTP/MCP 服务，不连接隔离实验室或任何生产 Gateway。本分支保持为与其他研究入口平行的适配实现，不在这里合并那些分支。

```bash
python -m unittest discover -v
```
