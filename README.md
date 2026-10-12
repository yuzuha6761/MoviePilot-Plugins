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
| [下载器路径映射](plugins.v3/windowsqbsmb) | 将 Windows qBittorrent 返回路径转换为 Linux 风格，并在下载下发、修改保存位置时反向转换，支持多下载器和多条前缀映射。 |

## 路径转换配置

先在 MoviePilot 中配置并启用 Windows 版 qBittorrent 下载器，再打开插件设置：

| 配置项 | 示例 |
| --- | --- |
| 下载器（可多选） | 自动列出已启用的 qBittorrent 下载器，选择需要转换返回路径的下载器 |
| 映射关系 | 点击“添加映射”新增，通过下拉框切换编辑，或点击“删除映射”移除当前条目 |
| 转换前路径前缀 | `E:\qBittorrent_download` |
| 转换后路径前缀 | `/downloads` |

以上配置会将返回路径 `E:\qBittorrent_download\电影\A.mkv` 转换为 `/downloads/电影/A.mkv`。
下载下发或修改保存位置时反向应用同一条规则，将 `/downloads/电影` 转换为 `E:/qBittorrent_download/电影`。
“转换前”“转换后”以下载器返回路径的方向命名。
匹配按完整目录段进行，Windows 前缀忽略大小写，后缀大小写保持原样。输入支持反斜杠、正斜杠及混用，输出统一使用正斜杠。

所选下载器共用全部映射。转换前、后的两侧路径前缀均不能重复或互相包含，以保证反向转换唯一。
若下载器返回的临时目录在已有前缀范围外，另加一条映射；返回或下发路径未匹配时会提示错误。
配置完成后启用插件，点击页面底部“保存”生效。

插件转换下载器返回路径，以及下载下发、修改保存位置时传入的路径字符串；不参与 MoviePilot 对返回路径的后续处理。
当前适配 **MoviePilot 3.1.4**，启用时会检查宿主接口兼容性。
开发与测试说明见 [设计文档](docs/design.md)。
