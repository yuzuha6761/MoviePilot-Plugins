# MoviePilot V3 插件仓库

MoviePilot V3 第三方插件仓库。

## 安装

将以下地址添加到 MoviePilot 的插件市场配置（`PLUGIN_MARKET`），刷新插件市场后安装所需插件。多个仓库地址用英文逗号分隔。

```text
https://github.com/yuzuha6761/moviepilot-v3-plugins
```

## 插件列表

| 插件 | 说明 |
| --- | --- |
| [Windows qBittorrent 路径映射](plugins.v3/windowsqbsmb) | Windows 下载路径与 MoviePilot 本地或 SMB 存储路径双向映射，支持混合斜杠和临时目录，无需修改 MoviePilot 镜像。 |

## 路径映射配置

先在 MoviePilot 中配置好 qBittorrent 下载器和对应存储，再打开插件设置：

| 配置项 | 示例 |
| --- | --- |
| 下载器配置名称 | 与 MoviePilot 中的下载器名称一致 |
| Windows 下载根路径 | `E:/qBittorrent_download` |
| MoviePilot 存储路径 | 本地填 `/downloads` 或 `local:/downloads`；SMB 单共享填 `smb:/`，多共享填 `smb:/qBittorrent_download` |

MoviePilot 下载目录选择对应的**本地**或 **SMB** 存储，目录填写 `/downloads`、`/` 或 `/qBittorrent_download/`，然后启用插件。
本地路径指 MoviePilot 容器或进程能访问的目录，需事先挂载并与 Windows 下载目录对应；插件不负责挂载或复制文件。
若未完成目录在主映射范围外，需成对填写 Windows 临时目录和对应的存储路径，两条映射不能重叠。

当前适配 **MoviePilot 3.1.4**，启用时会检查宿主接口兼容性。开发与测试说明见 [设计文档](docs/design.md)。
