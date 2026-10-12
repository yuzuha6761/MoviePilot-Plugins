# 下载器路径映射：设计记录

## 功能与边界

将运行在 Windows 上的下载器返回的种子路径转换为 MoviePilot 可识别的路径，当前适配 qBittorrent 和 Transmission，
并在下载下发、修改保存位置时反向应用同一组前缀映射。
例如配置 `E:\Downloads` → `/downloads`，返回 `E:\Downloads\Movie\A.mkv` 时输出 `/downloads/Movie/A.mkv`。
只处理路径字符串，不查询文件是否存在，也不参与 MoviePilot 的后续文件处理。

插件分别包装 `QbittorrentModule`、`TransmissionModule` 的 `normalize_return_path` 和 `normalize_path`，
不修改它们共享的基类。只安装所选下载器对应类型的包装。
返回路径按“转换前 → 转换后”转换，下发和修改位置按相反方向转换；
Windows 输出使用正斜杠。未选择的下载器调用原方法。
不修改 MoviePilot 镜像、下载器配置或 SMB 归属校验。

## 已核对的宿主基线

MoviePilot V3 `99ef7e508b829e81cedaf55b3aea0387baca2515`（声明版本 3.1.4），
前端 `55c1121bfc145964ee7e826de70bec4f7f1c0f5a`；未读取用户实际镜像版本。

```text
download / update_torrent → normalize_path → qBittorrent / Transmission 客户端
qBittorrent / Transmission 任务信息 → Path 构造或目录拼接 → normalize_return_path → DownloaderTorrent
```

任务查询在转换前只构造 `Path` 或拼接目录，反斜杠仍被保留，因此在返回路径入口统一转换。
Transmission 使用 `download_dir` 与种子名称拼接内容路径，并将 `download_dir` 作为保存路径；两者均经过返回路径转换。
不包装下载器客户端数据、不改写缓存对象、不额外返回任务列表。
仅覆盖 MoviePilot 内置 qBittorrent、Transmission 模块，第三方插件直接调用客户端不在覆盖范围内。

## 前缀转换

`mapping.py` 无宿主依赖，按完整目录段匹配转换前前缀，支持两种斜杠及混用。
Windows 前缀不区分大小写；输出前缀和后缀保留各自大小写。拒绝相对路径、目录穿越、NUL 等非法输入。
多个转换前前缀或转换后前缀均不能重复、互相包含，否则反向转换无法唯一确定 Windows 路径。
反向匹配 Linux 前缀区分大小写，SMB 前缀不区分大小写；不同前缀类型互不匹配。
未匹配的返回或下发路径报错，提示补充对应方向的前缀映射。

POSIX `Path` 会将盘符根 `E:/` 折叠为 `E:`。仅在输入是 `Path` 且显式配置了该盘符根时恢复尾斜杠，
比较配置前先统一分隔符，因此 `E:\` 配置也能正确处理。裸字符串 `E:` 仍按相对路径拒绝。
反向转换也会恢复 POSIX `Path` 折叠后的 `local:`、`smb:` URI 根。

## 配置与表单

`app.sdk.services.ServiceConfigHelper` 自动列出已启用的 qBittorrent 和 Transmission 下载器。
`downloaders` 保存多选名称，支持两种类型混选；同一名称跨类型重复时拒绝启用。
明确指定名称或宿主默认下载器名称命中当前类型的已选列表时转换。
宿主默认下载器是跨类型的全局配置，仍由原模块查找实例；默认配置属于另一类型时，该模块不下发任务。
所有选中下载器共用 `mappings` 列表，每条包含 `windows_root`、`storage_root`，
分别对应“转换前路径前缀”和“转换后路径前缀”。临时目录按普通映射添加。
配置仅使用这一种结构，不提供旧格式迁移。表单默认值与宿主保存的当前配置合并后展示。
转换后前缀支持绝对路径及 URI：`local:/` 前缀输出 `/`，`smb:/` 前缀保留原文本，
不负责识别或连接实际存储。

表单使用 `VSelect` 切换映射、输入框编辑当前项，以及添加/删除按钮。
根据上述前端基线的 `FormRender.vue`，数组项通过 `modelValue` 表达式与
`onUpdate:modelValue` 写回，`mapping_index` 仅记录编辑位置。

## 生命周期与兼容检查

内部接口适配集中在 `runtime.py`。保留版本与两个转换入口的签名检查；
`compatibility.py` 校验 `download`、`update_torrent`、`list_torrents`、`init_module`、
`get_default_config_name`、`normalize_path`、`normalize_return_path` 七个方法的 AST 摘要，按下载器类型分别保存。
qBittorrent 沿用原有摘要；Transmission 新增对应模块方法的摘要，共用继承方法的摘要。
AST 使用固定字段序列化，兼容 Python 3.12 与 3.14 的空字段差异；无法取得源码时拒绝接管。

包装器记录原方法与所有权。停用后仅恢复本插件仍持有的包装，保留后来安装的第三方包装。
被其他插件保留的旧包装停用后透传。支持重复初始化、实例重建和类重载；
每 30 秒重新核对宿主契约并迁移重载后的类，检查失败撤销适配。
插件生命周期与定时检查串行化，转换和包装安装使用锁保护。
第二个插件实例争用同一入口时拒绝安装。所有已选类型通过检查后统一安装；
任一包装安装失败时撤销本次所有类型已安装的包装。下载器类型改变或模块类重载时重新分组并迁移包装。

## 验证

使用 Python 3.12 或更高版本运行标准库测试，全部宿主接口使用替身，不连接真实服务：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins.v3 tests tools
git diff --check
```

表单事件测试通过 Node 执行已核对的宿主表达式/事件语义；没有 Node 时跳过该项。
已有可信本地宿主源码时可执行原方法隔离回归：

```bash
python3 tools/check_upstream.py /path/to/MoviePilot
```

脚本从源码提取原方法，不导入真实宿主。检查返回路径、多个下载器及前缀、盘符根、
不同任务状态和缺少内容路径的回退，验证下载下发和保存位置参数的反向转换；
使用替身核对原 SMB 归属校验仍有效，不连接真实服务。

仍待实机验证 Windows qBittorrent、Transmission 的任务返回值、宿主页面和调度生命周期。
不自动发布插件、改动用户任务或移动文件。

## 0.2.1 验证记录（2026-10-12）

- 环境：macOS ARM64、Python 3.12.15、Node 26.5.1。
- 49 项单元测试通过，无跳过项；移除旧配置迁移后，测试统一使用当前配置结构，覆盖双向转换、两个包装入口的生命周期、输出前缀歧义拒绝、盘符根、Linux 大小写及 URI 前缀。
- 固定宿主源码的 6 项隔离回归通过，覆盖下载下发、修改保存位置、任务返回路径、多个下载器及映射、盘符根和原 SMB 归属校验。
- `compileall`、`git diff --check` 通过；未进行实机或部署验证，未连接真实服务，未发布插件。

## 0.2.2 路径匹配诊断（2026-10-12）

未匹配时显示转换方向、待匹配路径和当前方向的配置前缀；运行时入口补充实际选中的下载器名称。
保持本地/SMB 类型和目录边界匹配规则，未匹配路径继续报错，不调用原方法绕过映射。
表单补充本地与 SMB 前缀示例，便于核对宿主下发的路径类型。

已核对宿主模块调度器会捕获转换异常；下载提交逻辑在没有下载结果时使用“未找到下载器”作为兜底提示。
该提示不能替代堆栈中的路径错误。仅凭不含实际路径的旧日志，无法判断具体是哪条配置不匹配。

macOS ARM64、Python 3.12.15、Node 26.5.1 下，50 项单元测试、7 项固定源码隔离回归通过，无跳过项。
新增回归确认本地路径与 SMB 前缀不匹配时，在向 qBittorrent 下发或修改位置前报错，并包含定位信息。
`compileall`、`git diff --check` 通过。未连接真实服务、部署或发布，诊断改进不代表已解决用户的实际配置问题。

## 0.2.3 Transmission 支持（2026-10-12）

- 环境：macOS ARM64、Python 3.12.15、Node 26.5.1。
- 60 项单元测试通过，无跳过项；新增 Transmission 单选、两种类型混选、类型隔离、默认下载器、重复启停、类重载、类型变更、重名拒绝、跨类型安装失败回滚及第三方包装保留验证。
- 固定 MoviePilot 3.1.4 源码的 11 项隔离回归通过，使用生产摘要检查；新增 Transmission 下载下发、保存位置修改、各查询状态的返回路径、本地/SMB/盘符根映射、未选下载器透传、全局默认下载器切换和不匹配时阻止下发验证。
- `compileall`、`git diff --check` 通过。未连接真实下载器或存储，未进行实机或部署验证，未发布插件。
