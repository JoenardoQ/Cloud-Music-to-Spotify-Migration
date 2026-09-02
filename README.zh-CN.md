# Cloud Playlist Bridge

[English](README.md) · [用户指南](USER_GUIDE.zh-CN.md)

把你有权访问的网易云音乐公开歌单迁移到 Spotify。程序在本机读取歌单元数据、搜索
Spotify 曲库并生成可审查的匹配计划；只有你最后确认后，它才会创建 Spotify 歌单。

它不会下载音频、破解会员内容、读取私有歌单，也不会绕过地区或版权限制。

## 它能做什么

- 按网易云歌单原顺序处理歌曲。
- 根据歌名、歌手、专辑、时长和版本标记匹配 Spotify 曲目。
- 自动写入高置信度结果，跳过歧义、低置信度和未找到的歌曲。
- 输出完整 CSV、手动添加 CSV 和带校验和的迁移计划。
- 保存匹配和写入进度，中断后可继续。
- 提供本地网页 App，也提供无需 App 页面即可使用的 `plan` / `apply` 命令。
- 支持 Windows、macOS 和 Linux；运行时只使用 Python 标准库。

## 使用前准备

你需要：

- Python 3.11 或更高版本；
- Spotify Premium 账户；
- 自己创建的 Spotify Developer 应用及其 Client ID；
- 一个无需登录即可打开的网易云音乐公开歌单；
- 首次安装、读取歌单、Spotify 授权和迁移时可用的网络连接。

Spotify 开发模式要求应用所有者保持 Premium，并限制授权用户和 API 配额。个人使用时，
建议使用自己账户创建的 Client ID。详见 Spotify 官方的
[开发模式规则](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)。

## 选择使用方式

| 方式 | 适合谁 | 是否打开本地 App 页面 |
| --- | --- | --- |
| 本地 App | 希望填写表单、查看实时进度的用户 | 是 |
| 纯命令行 | 希望通过 CMD、终端或脚本运行的用户 | 否 |
| 图形启动器 | 已安装应用，希望以后从开始菜单或应用目录启动的用户 | 是 |

三种方式使用同一套迁移逻辑。纯命令行首次授权 Spotify 时仍会打开或打印 Spotify 登录
网址；这是 OAuth 身份验证，不是本地 App 页面。

## 1. 下载项目

打开 [GitHub 项目页](https://github.com/JoenardoQ/Cloud-Music-to-Spotify-Migration)，
点击 **Code → Download ZIP**，然后解压。后续命令都要在解压后的项目文件夹中运行。

如果你不熟悉文件夹、CMD 或终端，请直接阅读
[用户指南](USER_GUIDE.zh-CN.md)。

## 2. 安装 Python 环境和应用

项目目前从下载的源码安装到项目文件夹内独立的 `.venv` 环境。安装 Python 或 Ubuntu
系统软件包时可能需要管理员授权，但应用本身不会安装到整个系统。

### Windows（CMD）

1. 从 [Python Windows 下载页](https://www.python.org/downloads/windows/)安装
   Python 3.11 或更高版本；安装器显示 **Add python.exe to PATH** 时请勾选。
2. 用文件资源管理器打开项目文件夹，点击地址栏，输入 `cmd`，按回车。
3. 在黑色 CMD 窗口中逐行运行：

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install .
```

### macOS

1. 从 [Python macOS 下载页](https://www.python.org/downloads/macos/)安装
   Python 3.11 或更高版本。
2. 打开“终端”，输入 `cd `，把项目文件夹拖进终端，然后按回车。
3. 逐行运行：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install .
```

### Ubuntu / Debian

在项目文件夹中打开终端，逐行运行：

```bash
sudo apt update
sudo apt install -y python3 python3-venv
python3 -m venv .venv
./.venv/bin/python -m pip install .
```

本文后续始终显式调用 `.venv` 中的 Python，因此不需要执行 `activate`，也不会误用系统
中的另一个 Python 环境。

## 3. 准备 Spotify Client ID

1. 登录 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)。
2. 创建一个应用；名称和描述可以自定。
3. 在应用设置中登记下面这个 Redirect URI，必须逐字一致：

   ```text
   http://127.0.0.1:8888/callback
   ```

4. 保存设置并复制 **Client ID**。

程序使用 Authorization Code with PKCE，不需要 Client Secret。不要把 Client Secret
填入程序或发给别人。Spotify 要求回调地址使用明确的回环 IP；不要把 `127.0.0.1`
改成 `localhost`。参见 Spotify 官方的
[Redirect URI 规则](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)。

## 4. 使用本地 App

### 启动

Windows CMD：

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge app --no-browser
```

macOS 或 Linux：

```bash
./.venv/bin/python -m cloud_playlist_bridge app --no-browser
```

看到下面的地址后，保持 CMD 或终端开启，并在浏览器中打开它：

[http://127.0.0.1:8765/](http://127.0.0.1:8765/)

`--no-browser` 只是不让系统自动打开浏览器，不影响 App 运行。服务只允许监听本机回环
地址，其他设备不能通过局域网访问。

### 迁移歌单

1. 粘贴网易云歌单分享链接或纯数字歌单 ID。
2. 粘贴 Spotify Client ID。
3. 点击“分析歌单”，并在 Spotify 页面完成授权。
4. 等待匹配结束，查看匹配和跳过数量；需要时下载手动添加名单。
5. 确认结果后，点击“创建 Spotify 歌单”。

“分析歌单”只读取、搜索并写入本地计划，不会创建 Spotify 歌单。只有最后一步会产生
Spotify 写入。默认创建公开歌单；要创建私有歌单，请在分析前打开“高级设置”并勾选
“创建为私有歌单”。

### 高级选项

- `本地 api-enhanced`：改用你自己运行的兼容服务读取网易云；普通用户留空。
- `预期歌曲数`：你已知网页显示数量时可填写；数量不一致会停止，避免静默漏歌。
- `最低评分`：默认 `0.82`。
- `歧义差距`：默认 `0.05`。
- `允许残缺迁移`：网易云缺少个别歌曲详情时，允许跳过这些歌曲继续。

不要在不理解后果时降低匹配阈值。低阈值会增加写入错误版本或错误歌曲的风险。

## 5. 使用纯命令行

纯命令行分成两个明确阶段：`plan` 生成并审查计划，`apply` 才写入 Spotify。

### 生成或恢复计划

Windows CMD：

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge plan "https://music.163.com/playlist?id=123456789" --spotify-client-id YOUR_CLIENT_ID
```

macOS 或 Linux：

```bash
./.venv/bin/python -m cloud_playlist_bridge plan 'https://music.163.com/playlist?id=123456789' --spotify-client-id YOUR_CLIENT_ID
```

把示例歌单地址和 `YOUR_CLIENT_ID` 换成自己的值。也可以用纯数字歌单 ID。

网易云缺少歌曲详情时，默认会停止并列出能获得的歌曲名、歌手、发布时间和 ID。如果你
接受跳过这些歌曲，可在 `plan` 命令末尾添加：

```text
--allow-incomplete-source
```

### 查看输出

`plan` 默认在 `reports` 文件夹生成三个文件：

```text
<名称>-<歌单ID>-<计划ID>.plan.json   带校验和的固定执行计划
<名称>-<歌单ID>-<计划ID>.csv         每首歌曲的完整匹配报告
<名称>-<歌单ID>-<计划ID>.manual.csv  所有跳过歌曲及最多三个候选链接
```

先检查 CSV。`matched` 表示会自动写入；`ambiguous`、`low_confidence` 和
`not_found` 都会跳过。计划生成后，`apply` 不会重新搜索或改变匹配结果。

### 执行计划

Windows CMD：

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge apply "reports\NAME.plan.json" --spotify-client-id YOUR_CLIENT_ID --private
```

macOS 或 Linux：

```bash
./.venv/bin/python -m cloud_playlist_bridge apply 'reports/NAME.plan.json' --spotify-client-id YOUR_CLIENT_ID --private
```

把 `NAME.plan.json` 换成实际文件名。删除 `--private` 时会创建公开歌单；也可以明确写
`--public`。安装后可用较短的 `cloud-playlist-bridge` 命令，但显式解释器形式最不依赖
PATH 或终端环境。

常用环境变量：

```text
SPOTIFY_CLIENT_ID       代替 --spotify-client-id
NETEASE_API_BASE_URL    代替 --netease-api-base-url
```

## 残缺迁移与匹配结果

网易云歌单的 `trackIds` 决定完整数量和顺序。如果网易云没有返回某些歌曲的详情，程序
默认在 Spotify 搜索前停止，因为继续可能造成漏歌、错序或错误匹配。

只有你在 App 勾选“允许残缺迁移”或在 CLI 添加 `--allow-incomplete-source` 后，程序才会
继续。缺失歌曲会保留原位置、标记为 `not_found` 并进入手动报告，但不会发送到
Spotify 搜索，也不会写入 Spotify 歌单。

其他不确定结果同样严格跳过。程序不会让你在 App 中逐首强制接受候选；如需补歌，请
根据 `manual.csv` 中的候选链接在 Spotify 手动处理。

## 中断、恢复与文件位置

- 规划进度保存在 SQLite 检查点中。使用相同歌单和相同匹配设置再次运行会复用已保存
  结果。
- Spotify 每批最多写入 100 首。`apply` 中断后，再次执行同一个计划会读取执行日志、
  核对远端歌单并继续，避免盲目重复创建或重复添加。
- 如果远端歌单被手动改动，程序可能停止并要求你检查，而不是猜测正确状态。
- App 或 CLI 默认把令牌和检查点写入项目下的 `.state`，把计划和报告写入 `reports`。

关闭 App：回到运行它的 CMD 或终端，按 `Ctrl+C`。下次不需要重新安装，直接重复启动
命令即可。

## 可选图形启动器

安装完成后，可创建当前系统的启动器。

Windows CMD：

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge install-launcher
```

macOS 或 Linux：

```bash
./.venv/bin/python -m cloud_playlist_bridge install-launcher
```

- Windows：开始菜单“程序”目录中的 `Cloud Playlist Bridge.vbs`；数据位于
  `%LOCALAPPDATA%\Cloud Playlist Bridge`。
- macOS：`~/Applications/Cloud Playlist Bridge.app`；数据位于
  `~/Library/Application Support/Cloud Playlist Bridge`。
- Linux：`~/.local/share/applications/cloud-playlist-bridge.desktop`；数据位于
  `~/.local/share/cloud-playlist-bridge`。

启动器记录安装时的 Python 路径。移动项目文件夹、删除 `.venv` 或重建环境后，需要
重新运行 `install-launcher`。

## 网易云读取方式

默认方式直接读取网易云公开网页使用的只读接口，无需网易云账号或 Cookie，但该接口
不是稳定的官方开放平台契约，网易云改版后可能失效。

高级用户可以通过 `--netease-api-base-url http://127.0.0.1:3000` 或 App 高级设置使用
自己运行的 `api-enhanced` 兼容服务。该类服务是第三方逆向实现，不是网易云官方 API；
请只使用可信的本机实例，不要把 Cookie 发送到公共实例。

## 常见问题

### `Address already in use`

端口 `8765` 已被占用，或者 App 已经在另一个窗口运行。先尝试打开
`http://127.0.0.1:8765/`。如果打不开，可换端口：

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge app --no-browser --port 8766
```

macOS/Linux 把命令前缀换成 `./.venv/bin/python`，然后打开
`http://127.0.0.1:8766/`。

### `gio: Operation not supported`

这通常只表示系统不能自动打开浏览器。使用 `--no-browser` 启动并手动打开终端打印的
地址。

### Spotify 回调端口无法监听或 Redirect URI 不匹配

确认 Developer Dashboard 中登记的是
`http://127.0.0.1:8888/callback`。关闭占用端口 `8888` 的其他程序后再试。

### Spotify 返回 403、429 或配额暂停

确认应用所有者仍是 Premium，当前登录用户已获准使用该开发模式应用。429 可能是短期
速率限制，也可能是开发模式配额耗尽；程序会保存规划进度，稍后用相同命令恢复。

### 网易云歌单无法读取

先在退出登录或隐私浏览窗口中打开歌单。私有、仅自己可见或必须登录的歌单不受默认
读取方式支持。公开接口发生变化时，也可能需要等待项目适配。

## 隐私与安全

- `.state/spotify-token.json` 含 Spotify 登录令牌，不要分享或提交到 Git。
- `reports` 含歌单名、歌曲元数据和匹配候选，不要在未检查前公开上传。
- 程序不需要 Spotify Client Secret，也不应接收网易云 Cookie。
- 本地 App 默认只监听 `127.0.0.1`，并对写请求检查 CSRF token。
- `.state`、`reports`、虚拟环境和构建产物已由项目的 `.gitignore` 排除。

## 限制

- 只迁移歌单元数据，不迁移音频、收藏时间、评论或播放历史。
- 默认只支持无需登录即可读取的网易云公开歌单。
- 跨平台元数据匹配无法证明两个条目是同一录音，人工复核仍有必要。
- Spotify 搜索没有批量接口，大歌单可能耗时较长并触发速率或开发模式配额限制。
## 开发者入口

普通用户不需要本节。架构、数据流、不变量和失败语义见
[docs/architecture.zh-CN.md](docs/architecture.zh-CN.md)。离线验证命令：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```
