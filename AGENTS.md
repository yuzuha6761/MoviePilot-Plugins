# 开发规范

## 项目约定

- 文档、注释及用户提示以简明中文为主。
- 插件位于 `plugins.v3/<插件 ID 小写>/`，入口类名与 `package.v3.json` 中的 ID 一致。
- 插件入口、仓库索引与项目元数据中的版本号保持一致，更新记录与版本对应。
- 优先使用 `app.sdk` 公开接口；内部接口适配集中在 `runtime.py`，保留版本与签名检查。
- 功能通过插件实现，不修改 MoviePilot 官方镜像或生产配置。

## 路径与运行时

- 路径按完整目录段匹配；Windows 根路径比较忽略大小写，保留后缀大小写；本地存储路径区分大小写。
- 远程 Windows 路径不调用宿主本地 `Path.exists()`、`Path.stat()`，保留 SMB 路径归属校验。
- 运行时适配仅作用于配置的下载器，覆盖启停、重复初始化、模块重载、包装冲突及卸载恢复。

## 验证

使用标准库 `unittest`，宿主接口通过测试替身隔离，不访问真实下载器、SMB、MoviePilot、数据库或网络。

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins.v3 tests tools
git diff --check
```

验证记录应注明环境与范围，区分单元测试、隔离回归和部署验证。
开发与测试不自动发布插件、修改用户任务、移动用户文件或连接生产服务。
