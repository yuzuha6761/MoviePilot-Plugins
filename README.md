# MoviePilot V3 插件仓库

MoviePilot V3 第三方插件仓库。

## 安装

将以下地址添加到 MoviePilot 的插件市场配置（`PLUGIN_MARKET`），刷新插件市场后安装所需插件。多个仓库地址用英文逗号分隔。

```text
https://github.com/yuzuha6761/MoviePilot-Plugins
```

## 插件列表

| 插件 | 说明 |
| --- | --- |
| [下载器路径映射](plugins.v3/windowsqbsmb) | 将 Windows qBittorrent 下载路径与 MoviePilot 本地或 SMB 存储路径双向映射，支持多下载器、多条映射及临时目录。 |

## 路径映射配置

先在 MoviePilot 中配置好 qBittorrent 下载器和对应存储，再打开插件设置：

| 配置项 | 示例 |
| --- | --- |
| 下载器（可多选） | 自动列出已启用的 qBittorrent 下载器，选择需要映射的下载器 |
| 映射关系 | 点击“添加映射”新增，通过下拉框切换编辑，或点击“删除映射”移除当前条目 |
| Windows 下载根路径 | `E:/qBittorrent_download` |
| MoviePilot 存储路径 | 本地填 `/downloads` 或 `local:/downloads`；SMB 单共享填 `smb:/`，多共享填 `smb:/qBittorrent_download` |

MoviePilot 下载目录选择对应的**本地**或 **SMB** 存储，目录填写 `/downloads`、`/` 或 `/qBittorrent_download/`，然后启用插件。
本地路径指 MoviePilot 容器或进程能访问的目录，需事先挂载并与 Windows 下载目录对应；插件不负责挂载或复制文件。
所选下载器共用全部映射，因此应选择路径布局相同的下载器。可添加多条映射，每条填写一组 Windows 路径和对应存储路径；任意两条映射的 Windows 根路径或同类存储根路径均不能重叠。
若未完成目录在已有映射范围外，另加一条对应映射。修改后点击页面底部“保存”生效。
旧版的单下载器、主目录和临时目录配置会自动显示为新表单；清空选择或删除映射后不会恢复旧值。

当前适配 **MoviePilot 3.1.4**，启用时会检查宿主接口兼容性。开发与测试说明见 [设计文档](docs/design.md)。
