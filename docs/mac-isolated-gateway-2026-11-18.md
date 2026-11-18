# Mac mini 隔离 Gateway 实机补充（2026-11-18）

这是一份新增补充，不改写已有历史调查或 Linux 解包验证文档。先前 main 上的 [8.3.9 运行时验证](runtime-validation-8.3.9.md) 与 [2027.2.0-beta1 运行时验证](runtime-validation-2027-beta1.md) 使用的是官方 OCI 在 Linux 上解包运行的证据，不是这台 Mac 上的隔离 Docker Gateway。本文件记录的是 wubindeMac mini 上隔离容器的实机结果。

未提交第三方模块二进制、凭据、Cookie、CSRF、会话 ID 或 API token 密钥。未改动、重启或探测生产性质的 `/usr/local/ignition`（pid 1373，监听 `*:8088` 与 `*:8060`）。

## 已起来的隔离 8.3.9

官方镜像 `inductiveautomation/ignition:8.3.9`（`linux/arm64`，image/repo digest `sha256:28bd6b320157ec8dbbe465d0cd7c9f0ababfda4ff01c0bab982c0522a7b4eba2`，镜像创建于 2026-08-25 18:34:45Z）已在本机以容器 `ignition-harness-8-3-9`（id 前缀 `2a2eff3d4c78`）运行。该容器于 2026-11-18 10:12:21（Asia/Singapore）启动，健康检查为 healthy。端口仅绑定本机回环：

- `127.0.0.1:28088` → 8088
- `127.0.0.1:28060` → 8060
- `127.0.0.1:28443` → 8043

`GET http://127.0.0.1:28088/StatusPing` 返回 200，`{"state":"RUNNING"}`。`GET /system/gwinfo` 返回 200，关键字段：`Version=8.3.9`，`PlatformName=ignition-harness-8-3-9`，`ContextStatus=RUNNING`，`RuntimeVersion=17.0.19`，`OS=Linux`，`RequireSsl=false`，`AllowDesignerSSO=false`。容器内 `commissioning.json` 为已 commissioning。首页标题为 `ignition-harness-8-3-9`。数据卷为 `ignition-harness-8-3-9-data`。原始脱敏记录：[evidence/mac-mini-isolated/8.3.9-status-2026-11-18.json](evidence/mac-mini-isolated/8.3.9-status-2026-11-18.json)。

匿名探测（无认证头，也未编造 Designer 登录/续期 API）：`/StatusPing` 200，`/system/gwinfo` 200，`/openapi.json` 403 Forbidden，`/mcp` 404 Not Found。`data/modules.json` 共 29 个官方模块，**未安装 Artek-MCP**，因此这台 8.3.9 上没有可探测的 `/mcp`，无法采集实机 `tools/list`。容器日志 10:12:28 `Trial time reset. Time remaining = 7200.`，10:12:33 `Could not read license from HASP key. Driver not found`。未许可试用约到 2026-11-18 12:12（Asia/Singapore）。该隔离 8.3.9 容器在后续已认证验证期间仍保持健康运行。

## 8.3.9 认证、OpenAPI 与 View 写入/预览/恢复

登录同样走官方 IdP 与 Web 会话 + CSRF，没有编造 Designer 登录或续期 API。已认证 OpenAPI 为 580 条路径、679 个操作，高于先前 Linux 解包环境的 389 条路径。摘要：[evidence/mac-mini-isolated/8.3.9-openapi.summary.json](evidence/mac-mini-isolated/8.3.9-openapi.summary.json)。认证说明（无密钥）：[evidence/mac-mini-isolated/8.3.9-auth-and-openapi.redacted.json](evidence/mac-mini-isolated/8.3.9-auth-and-openapi.redacted.json)。

8.3.9 的 Tag API 不能照搬 2027 Beta：本轮使用已验证的配置导入/导出路径，而不是 `/tags/configuration`、`/tags/read`、`/tags/write`。导入 Memory Tag 的 value 不能包装成已验证的通用运行值写入 API。步骤见 [evidence/mac-mini-isolated/8.3.9-view-write-preview-restore.json](evidence/mac-mini-isolated/8.3.9-view-write-preview-restore.json)。摘要：

1. `POST /data/api/v1/projects` 创建项目 `HarnessLab`（200）。
2. `POST /data/api/v1/projects/import/HarnessLab?overwrite=true` 导入夹具（保留原生 `project.json` / `global-props`，合并 `research/fixtures/project-additions`）。Gateway 日志 2026-11-18 11:10:04（Asia/Singapore）出现 `HARNESS_LAB_STARTUP_V1_VERIFIED collection=HarnessLab`。
3. `POST /data/api/v1/tags/import?provider=default&type=json&collisionPolicy=Abort`，Content-Type `application/octet-stream`，创建 Folder + Float8 Memory Tag，`successCount` 2。`GET /data/api/v1/tags/export?provider=default&type=json&path=HarnessLab` 读回 `value` 与 `defaultValue` 均为 `42.5`。
4. 在数据目录创建独立 SQLite 文件（`jdbc:sqlite:${data}/harnesslab.db`），表 `samples` 含三行合成数据：Pump A 42.5、Pump B 72.5、Pump C 88.5。`POST /data/api/v1/resources/ignition/database-connection` 的 OpenAPI 要求 JSON 数组，每项需 `name` 以及 `config.driver`、`config.translator`、`config.connectURL`。创建 `HarnessLabDB` 返回 200，`success=true`（11:10:58）。
5. 用 Chrome DevTools Protocol 截图。可见文字包括：`Ignition Harness — Database Preview`、`42.5`、`Script V2 OK: 42.5`，以及表格中的 Pump A/B/C。截图：[evidence/mac-mini-isolated/screenshots/8.3.9-perspective-42.5.png](evidence/mac-mini-isolated/screenshots/8.3.9-perspective-42.5.png)。页面 innerText 里同时出现过 `No Connection to Gateway` 与 `Connected: ignition-harness-8-3-9`；截图本身清楚显示了视图、Tag、脚本标签和数据表。
6. `POST /data/api/v1/tags/import?...&collisionPolicy=MergeOverwrite&path=HarnessLab` 将 Tag 写回 `21.5`（`successCount` 1），export 读回 `21.5`。再次截图可见 `21.5` 与 `Script V2 OK: 21.5`，表格三行仍在：[evidence/mac-mini-isolated/screenshots/8.3.9-perspective-restored-21.5.png](evidence/mac-mini-isolated/screenshots/8.3.9-perspective-restored-21.5.png)。

## 已起来的隔离 2027.2.0-beta1

官方镜像 `inductiveautomation/ignition:2027.2.0-beta1`（`linux/arm64`，image/repo digest `sha256:d34130f024296473aab1f0017b4d75870b02a9fbed56d18e0cdfff6804a88e50`，镜像 ID 前缀 `d34130f02429`，约 4.74GB，创建于 2026-11-02T21:32:04Z，build `b2026110221`）于 2026-11-18 约 10:50–10:52（Asia/Singapore）拉到本机。容器 `ignition-harness-2027-beta1`（id 前缀 `b1a7bd2a1392`）于 10:52:59 启动，Gateway 约 8 秒内起来，健康检查 healthy，`restartCount` 为 0。端口仅绑定本机回环：

- `127.0.0.1:18088` → 8088
- `127.0.0.1:18060` → 8060
- `127.0.0.1:18443` → 8043

数据卷 `ignition-harness-2027-beta1-data`。启动参数（不含密钥）：`ACCEPT_IGNITION_EULA=Y`，`IGNITION_EDITION=standard`，`DISABLE_QUICKSTART`，`-n ignition-harness-2027-beta1 -a localhost -h 18088 -s 18443 -m 1024`。匿名 `GET /StatusPing` 为 RUNNING；`/system/gwinfo` 为 `Version=2027.2.0-beta1`、`PlatformName=ignition-harness-2027-beta1`；匿名 `/openapi.json` 403，`/mcp` 404，`/` 302 到 `/Start`。Catalyst Core 与 Catalyst Agent 已启动。10:53:05 `LicenseManager` 将试用重置为 7200 秒；HASP 为 `Driver not found`（本机预期现象）。该 Beta 不得用于生产，现有许可证与该 Beta 不兼容。

脱敏状态记录：[evidence/mac-mini-isolated/2027.2.0-beta1-status-2026-11-18.json](evidence/mac-mini-isolated/2027.2.0-beta1-status-2026-11-18.json)。

## 2027 认证、OpenAPI 与 MCP tools/list

登录走官方入口：`GET /data/app/login` 转到本 Gateway 的官方 IdP；`authentication.js` 向 `/idp/default/authn/next-challenge` 与 `/idp/default/authn/submit-challenge/basic` 提交挑战，再经 `/idp/default/oidc/auth` 到达 `/data/federate/callback/internal`。随后用 Web 会话 Cookie 与 `GET /data/app/session` 取得的 CSRF 调用变更型 REST。没有编造 Designer 登录或续期 API。

已认证 OpenAPI 为 696 条路径、809 个操作，高于先前 Linux 解包环境的 455 条路径；官方 Docker 镜像在本机加载了完整官方模块集。摘要：[evidence/mac-mini-isolated/2027.2.0-beta1-openapi.summary.json](evidence/mac-mini-isolated/2027.2.0-beta1-openapi.summary.json)。认证说明（无密钥）：[evidence/mac-mini-isolated/2027.2.0-beta1-auth-and-openapi.redacted.json](evidence/mac-mini-isolated/2027.2.0-beta1-auth-and-openapi.redacted.json)。

Catalyst MCP 不接受 Web 会话，需要 `X-Ignition-API-Token`（`keyName:secret`）。token 通过本 Gateway OpenAPI 中的 `POST /data/api/v1/api-token/generate` 与 `POST /data/api/v1/resources/ignition/api-token` 创建；`securityLevels` 必须是本 Gateway OpenAPI / security-properties 中的对象树（Authenticated → Roles → Administrator），论坛常见的字符串形式 `Authenticated/Roles/Administrator` 在本机返回 422 且不会持久化 token。MCP server 通过 `POST /data/api/v1/resources/com.inductiveautomation.catalyst.agent/mcp-server-host` 创建。本轮 token 名为 `HarnessLabMac`，MCP server 名为 `HarnessLab`，端点为 `http://127.0.0.1:18088/data/catalyst-agent/mcp-servers/HarnessLab`，协议 `2025-06-18`。

`research/probe_mcp.py` 实机 `tools/list` 成功，发现 4 个工具：`diagnostics`、`realtime`、`query`、`providers`。工具名与 schema 与先前 Linux 解包证据一致。脱敏记录（含 schema，不含 token 或会话 ID，仅记录 `session_header_present: true`）：[evidence/mac-mini-isolated/2027.2.0-beta1-mcp-tools.redacted.json](evidence/mac-mini-isolated/2027.2.0-beta1-mcp-tools.redacted.json)。采集时间 2026-11-18 10:59:17（Asia/Singapore，对应 `2026-11-18T02:59:17Z`）。

## 2027 View 写入、预览与恢复

步骤与时间（Asia/Singapore）见 [evidence/mac-mini-isolated/2027.2.0-beta1-view-write-preview-restore.json](evidence/mac-mini-isolated/2027.2.0-beta1-view-write-preview-restore.json)。摘要：

1. `POST /data/api/v1/projects` 创建项目 `HarnessLab`。
2. `POST /data/api/v1/tags/configuration` 创建 Memory Tag `[default]HarnessLab/Temperature`（successCount 1）。
3. `POST /data/api/v1/projects/import/HarnessLab?overwrite=true` 导入夹具（保留原生 `project.json` / `global-props`，合并 `research/fixtures/project-additions`）。导入后立刻访问客户端路径曾短暂 404，稍后 `GET /data/perspective/client/HarnessLab` 返回 200。`/app/perspective/client/HarnessLab` 只是 Gateway SPA 外壳。
4. `POST /data/api/v1/tags/write` 写入 `42.5`（quality 192），`GET /data/api/v1/tags/read` 读回 `42.5`（2026-11-18 11:00:56 / `2026-11-18T03:00:56Z`）。Gateway 日志同时出现 `HARNESS_LAB_STARTUP_V1_VERIFIED collection=HarnessLab`。
5. 用 Chrome DevTools Protocol 等待页面出现 `42.5` 与 `Script V2` 后截图。可见文字包括：`Ignition Harness — Database Preview`、`42.5`、`Script V2 OK: 42.5`，以及按钮 `Run isolated Tag event test`。截图：[evidence/mac-mini-isolated/screenshots/2027-perspective-42.5.png](evidence/mac-mini-isolated/screenshots/2027-perspective-42.5.png)。表格显示 `ERROR`，因为本轮尚未在这台隔离 Gateway 上创建 `HarnessLabDB` SQLite 连接和 `samples` 表；Tag 与脚本标签仍能证明 View 写入和预览。页面 innerText 里同时出现过 `No Connection to Gateway` 与 `Connected: ignition-harness-2027-beta1`；截图本身清楚显示了视图、Tag 与脚本标签。
6. 将 Tag 写回 `21.5`（quality 192），`2026-11-18 11:03:47`（`2026-11-18T03:03:47.190Z`）读回 `21.5`。再次截图可见 `21.5` 与 `Script V2 OK: 21.5`：[evidence/mac-mini-isolated/screenshots/2027-perspective-restored-21.5.png](evidence/mac-mini-isolated/screenshots/2027-perspective-restored-21.5.png)。

## 尚未在这台 Mac 隔离环境完成的验收

- 8.3.9 实机 `tools/list`：仍被缺失的 Artek-MCP 阻塞（`/mcp` 404 为直接证据）。不要把模块二进制提交进仓库，也不要装到生产 Gateway。
- 可选：在隔离 2027 Gateway 上补建 `HarnessLabDB` 与 `samples` 表，以消除 2027 预览页表格的 `ERROR`。8.3.9 上该表已经跑通。

2027 在这台 Mac 隔离环境上的 `tools/list` 以及 View 写入/预览/恢复已经完成。8.3.9 在这台 Mac 隔离环境上的已认证 OpenAPI 与 View 写入/预览/恢复也已经完成（Tag 走 import/export 配置路径）。产品界面与薄适配层在 8.3.9 实机 MCP 仍缺模块的情况下，是否可以按已验证的 2027 Catalyst MCP 与两边原生 REST 推进，仍按仓库原有研究边界处理。未实现伪造的 Designer 登录客户端，现在也不做 Companion 模块。
