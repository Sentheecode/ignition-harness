# 真实运行实验使用的项目新增资源

`project-additions/` 是在 8.3.9 和 2027.2.0-beta1 实际导入并运行过的文本资源，不是完整项目导出，也不是 Harness 产品界面。

复跑只使用独立测试 Gateway 和自有项目：

1. 按对应运行报告创建 `HarnessLab`，导出其原生项目 ZIP，保留 project.json、global-props 及其他原始资源。
2. 创建 Float8 Memory Tag `[default]HarnessLab/Temperature`。Beta 使用 tags/configuration，8.3.9 使用 tags/import；请求形式见运行报告。
3. 创建独立 SQLite 表 `samples(id INTEGER PRIMARY KEY, label TEXT, reading REAL)`，加入三行合成数据；通过 Gateway 配置创建 `HarnessLabDB` SQLite 连接，确保 Valid。这里没有设备、生产库或外部服务。
4. 把本目录 project-additions 下的文件按相对路径合并进原生导出 ZIP，只对自有测试项目执行项目 import。使用 Web session + X-CSRF-Token 或目标 Gateway 授权的 API 身份，凭据放在仓库外。
5. 打开 `/data/perspective/client/HarnessLab`，确认 Tag/脚本 Label、数据库三行和按钮。点击按钮会将上述测试 Tag 写为 **91.5**，成功显示 `Event OK: Good`。导入还会启用 Gateway Startup 日志脚本。

夹具文件对应实验最后一次导入；热更新测试的 V1/V2 变化与结果见两份运行报告。未提供供应商二进制资源，不能丢弃原生导出里的 global-props。请勿把 ZIP 全量覆盖当作带资源签名的原子更新；仅在隔离测试项目复跑。
