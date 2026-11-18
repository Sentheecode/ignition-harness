# Mac mini 隔离 Gateway 实机补充（2026-11-18）

这是一份新增补充，不改写已有历史调查或 Linux 解包验证文档。先前 main 上的 [8.3.9 运行时验证](runtime-validation-8.3.9.md) 与 [2027.2.0-beta1 运行时验证](runtime-validation-2027-beta1.md) 使用的是官方 OCI 在 Linux 上解包运行的证据，不是这台 Mac 上的隔离 Docker Gateway。

采集时间：2026-11-18 10:19–10:22（Asia/Singapore）。主机：wubindeMac mini。原始脱敏记录：[evidence/mac-mini-isolated/8.3.9-status-2026-11-18.json](evidence/mac-mini-isolated/8.3.9-status-2026-11-18.json)。未提交第三方模块二进制、凭据或内部过程报告。未改动、重启或探测生产性质的 `/usr/local/ignition`（pid 1373，监听 `*:8088` 与 `*:8060`）。

## 已起来的隔离 8.3.9

官方镜像 `inductiveautomation/ignition:8.3.9`（`linux/arm64`，image/repo digest `sha256:28bd6b320157ec8dbbe465d0cd7c9f0ababfda4ff01c0bab982c0522a7b4eba2`，镜像创建于 2026-08-25 18:34:45Z）已在本机以容器 `ignition-harness-8-3-9`（id 前缀 `2a2eff3d4c78`）运行。该容器于 2026-11-18 10:12:21（Asia/Singapore）启动，健康检查为 healthy。端口仅绑定本机回环：

- `127.0.0.1:28088` → 8088
- `127.0.0.1:28060` → 8060
- `127.0.0.1:28443` → 8043

`GET http://127.0.0.1:28088/StatusPing` 返回 200，`{"state":"RUNNING"}`。`GET /system/gwinfo` 返回 200，关键字段：`Version=8.3.9`，`PlatformName=ignition-harness-8-3-9`，`ContextStatus=RUNNING`，`RuntimeVersion=17.0.19`，`OS=Linux`，`RequireSsl=false`，`AllowDesignerSSO=false`。容器内 `commissioning.json` 为已 commissioning。首页标题为 `ignition-harness-8-3-9`。数据卷 `ignition-harness-8-3-9-data` 中的 `projects` 目录只有 `.resources/.meta`，尚无 Perspective 项目或 View。

## 匿名 HTTP 与 MCP

匿名探测（无认证头，也未编造 Designer 登录/续期 API）：

| 路径 | 结果 |
|---|---|
| `/StatusPing` | 200 |
| `/system/gwinfo` | 200 |
| `/openapi.json` | 403 Forbidden |
| `/mcp` | 404 Not Found |
| `/data/perspective` | 404 Not Found |

匿名 `/openapi.json` 403 与 main 上 Linux 解包证据一致。本轮没有进行交互式登录，因此没有在这台隔离 Gateway 上取得已认证 OpenAPI，也没有做 View 写入、预览或恢复。

## 模块与许可

`data/modules.json` 共 29 个模块，均为 `com.inductiveautomation.*` 官方模块（含 Perspective 与 WebDev）。**未安装 Artek-MCP**。因此官方 8.3.9 镜像上不存在可探测的 `/mcp` 服务，无法在此环境采集实机 `tools/list`。Artek 模块二进制不会提交进本仓库；若要继续 8.3.9 + Artek 验证，需要操作者把已取得的 `.modl` 安装到这个隔离容器（不要装到生产 Gateway）。供应商下载页需要填写资料才能取得模块，此前 Linux 验证也因此未安装。

容器日志（Asia/Singapore）：

- 10:12:28 `LicenseManager`: `Trial time reset. Time remaining = 7200.`
- 10:12:33 `LicenseManager`: `Could not read license from HASP key. Driver not found`

未发现 HASP 许可。按日志，未许可试用从 10:12:28 起约两小时。

## 2027.2.0-beta1 在本机的状态

截至 2026-11-18 10:22（Asia/Singapore），本机还没有 `inductiveautomation/ignition:2027.2.0-beta1` 镜像，也没有对应隔离容器。已有进程 `docker pull --platform linux/arm64 inductiveautomation/ignition:2027.2.0-beta1`（pid 27492，约 10:10:33 开始）仍在进行。镜像就绪后，启动该隔离容器仍需操作者接受官方 Docker EULA（`ACCEPT_IGNITION_EULA=Y`）。该 Beta 不得用于生产，现有许可证与该 Beta 不兼容。

## 尚未在这台 Mac 隔离环境完成的验收

- 8.3.9 实机 `tools/list`：被缺失的 Artek-MCP 阻塞（`/mcp` 404 为直接证据）。
- 一次真实 View 写入 + 预览 + 恢复：被“尚未登录这台隔离 Gateway、且尚无 View 资源”阻塞，不是因为官方 API 不存在。Linux 解包环境已用已认证 OpenAPI 做过项目创建/导入与 Perspective 预览，见 [runtime-validation-8.3.9.md](runtime-validation-8.3.9.md)；本轮不把那次结果记成这台 Mac 隔离 Gateway 的实机结果。
- 2027.2.0-beta1 / Catalyst 在这台 Mac 上的 `tools/list` 与写入预览：被镜像仍在拉取、以及启动前的 EULA 确认阻塞。

产品界面与薄适配层在这台隔离环境完成 `tools/list` 以及 View 写入/预览/恢复之前保持阻塞。未实现伪造的 Designer 登录客户端，现在也不做 Companion 模块。
