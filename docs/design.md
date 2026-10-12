# Windows qBittorrent 路径映射：设计记录

## 基线与问题

MoviePilot V3 `99ef7e508b829e81cedaf55b3aea0387baca2515`（声明版本 3.1.4），
前端 `55c1121bfc145964ee7e826de70bec4f7f1c0f5a`；未读取用户实际镜像版本。

1. 下载器表单只允许 `/` 开头的路径，无法填写 Windows 盘符。
2. POSIX `Path` 不转换反斜杠，并会把 `smb:/` 折叠成 `smb:`。
3. SMB `_relative_path()` 拒绝没有尾反斜杠的共享根；标准 `/` 有提前处理分支。
4. 注册插件 `list_torrents` 会与宿主结果合并，不能作为替换手段。

## 0.1.0 实现

`mapping.py` 保持无宿主依赖，按完整目录段匹配、拒绝越界、保留后缀大小写。
`runtime.py` 是内部接口适配的唯一入口；配置发现与日志使用 `app.sdk`。

存储路径支持本地绝对路径（`/downloads`、`local:/downloads`）和 SMB URI。
Windows 路径返回时，本地映射输出 `/downloads/...`，SMB 映射保留 `smb:/...` 存储身份。
本地路径按大小写精确匹配，SMB 维持大小写不敏感；两种存储命名空间互不匹配。
为兼容已有配置，表单仍使用 `smb_root`、`smb_temp_root` 配置键，但标签与值已支持两类存储。
本地目录需由部署环境预先挂载，映射层不访问文件系统，不负责挂载或复制。

只在 `QbittorrentModule` 上增加 `normalize_path` 和 `normalize_return_path` 包装，
不修改所有下载器共用的基类。每次根据明确名称或宿主默认名称判断是否需要转换。
目标下载器只接受插件配置内的 Windows 路径与本地/SMB 存储路径；范围外直接报错。

经核对的调用顺序：

```text
download / update_torrent → normalize_path → qBittorrent 客户端
qBittorrent 任务信息 → Path 构造或目录拼接 → normalize_return_path → DownloaderTorrent
DownloaderTorrent.content_path → 字幕/整理的 URI 解析与父目录计算 → 本地或 SMB 存储
```

任务查询中转换前只有 `Path` 构造与拼接，尚未做父目录、文件名或本地存在性判断；
反斜杠在这一阶段仍保留，因此两个入口足以处理已审查的链路。
不包装 qBittorrent SDK 数据字典，不修改缓存对象，也不额外返回一份任务列表。
仅覆盖 MoviePilot 内置 qBittorrent 模块入口，第三方插件直接调用 qBittorrent 客户端不在覆盖范围内。

根路径返回规范的 `smb:/`，使下游查询 `/`。不对 SMB 做全局补丁，
不替换元数据查询结果，不吞掉连接/权限异常。其他调用方的非标准根路径缺陷仍保留。

## 生命周期与兼容检查

支持范围由 `compatibility.py` 固定：版本、七个方法的 AST 摘要，以及两个包装入口的签名。
摘要包含注释以外的 AST 内容，方法文档字符串也在范围内；不可获取源码时拒绝接管。
AST 使用固定字段序列化，避免 Python 3.12 与 3.14 的 `ast.dump` 默认空字段差异。
上游要求 Python >=3.14；本地离线验证运行于 3.12，CI 配置覆盖 3.12/3.14，尚未执行远程 CI。
更新摘要必须重新审查调用链并执行原方法回归，不能仅为绕过检查刷新摘要。

包装器持有独立的启用状态、原方法和原类属性所有权信息。卸载恢复继承关系，
不会用旧方法覆盖后来安装的包装；被第三方闭包保留的旧包装停用后只调用原方法。
实例重建不影响包装。Python 类重载通过宿主定时检查重新验证并迁移，有最多约 30 秒的
检查间隔，不能视为活动任务期间无缝热重载。契约检查失败撤销适配，需人工处理后重启用。

插件生命周期与定时检查串行化，适配层锁保护安装、转换和卸载。
不同插件实例争用同一入口时拒绝第二个实例，不叠加包装。

## 离线与实机边界

本地使用 Python 3.12 执行，无需安装 MoviePilot 或第三方依赖：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins.v3 tests tools
```

已有可信的本地 MoviePilot 源码时，可额外运行原方法隔离回归：

```bash
python3 tools/check_upstream.py /path/to/MoviePilot
```

标准库测试替代全部宿主边界。可选 `tools/check_upstream.py` 从可信本地源码提取原方法，
验证真实方法摘要、本地/SMB 映射的下载下发、修改保存路径、任务列表及 SMB 标准根连接校验；
不导入真实宿主、不访问网络或数据库。该验证不证明 qBittorrent、SMB 和 MoviePilot 部署可用。

仍待实机执行：

- 单文件/多文件种子，完成目录与未完成目录切换。
- 已有 Hash、分类保存路径、中文与空格路径。
- 字幕保存、单共享/多共享根查询、SMB 整理和做种文件保留。
- 本地挂载路径下的下载、字幕保存、整理与做种文件保留。
- 插件停用/重开、容器重启、下载器配置重载、另一个下载器不受影响。
- 安装流程及宿主调度器生命周期、实际镜像方法契约检查。

验证前保留原有可用下载器配置，不自动迁移在途任务，不连接生产服务。
