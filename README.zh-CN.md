# Cloud Playlist Bridge

[English](README.md)

Cloud Playlist Bridge 将用户有权访问的网易云音乐歌单元数据迁移到 Spotify。它不下载
音频、不破解会员内容，也不绕过地区或版权限制。

## 功能

- 本地单页 App：左侧网易云歌单，中间迁移进度，右侧 Spotify 结果，下方实时日志。
- 两阶段工作流：先分析并生成不可变计划，再由用户明确确认创建 Spotify 歌单。
- 以完整 `trackIds` 为准保留网易云源歌单顺序。
- 根据歌名、歌手、专辑、时长和版本标记进行可解释匹配。
- 严格拒绝歧义和低置信度结果；跳过的歌曲进入独立手动添加 CSV，并附候选链接。
- 使用 SQLite 检查点和搜索缓存支持 5,000–10,000 首的大歌单。
- Spotify 每批最多写入 100 首，支持失败后恢复。
- 保留可脚本调用的 `plan` 和 `apply` 命令。

## 环境要求

- Python 3.11 或更高版本。
- Spotify Premium。Spotify 2026 年开发模式规则要求应用所有者使用 Premium。
- 一个启用了 Web API 的 Spotify Developer 应用。
- 在应用中精确登记 Redirect URI：`http://127.0.0.1:8888/callback`。

运行时只使用 Python 标准库，不需要 Codex、ChatGPT、Agent、插件或 MCP 服务。

## 在 Ubuntu 安装

```bash
cd '/home/joenardo/My Projects/CloudMusic_to_Spotify_Migration'
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 在 Windows 安装

先安装 Python 3.11 或更高版本，然后在 PowerShell 中运行：

```powershell
cd 'C:\path\to\CloudMusic_to_Spotify_Migration'
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## 在 macOS 安装

先安装 Python 3.11 或更高版本，然后在“终端”中运行：

```bash
cd '/path/to/CloudMusic_to_Spotify_Migration'
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 本地 App

启动应用：

```bash
cloud-playlist-bridge app
```

程序只监听 `127.0.0.1`，并打开 `http://127.0.0.1:8765/`。在同一个页面内：

1. 输入网易云歌单 ID 或分享 URL，以及 Spotify Client ID。
2. 如有需要，输入本机自建的 `api-enhanced` 地址。
3. 点击“分析歌单”；如果浏览器打开 Spotify 授权页，请完成授权。
4. 查看已匹配和已跳过数量；歧义歌曲保持跳过。
5. 点击“创建 Spotify 歌单”，才会发生外部写入。

页面使用虚拟列表显示大歌单。关闭页面不会损坏检查点；重新启动 App 并分析相同歌单
即可恢复已保存的匹配进度。报告写入 `reports/`，状态写入 `.state/`。

常用 App 参数：

```text
app --host 127.0.0.1       回环地址；拒绝非回环地址
app --port 8765            本地页面端口
app --no-browser           不自动打开默认浏览器
app --state-dir .state     检查点和 Spotify 令牌目录
app --report-dir reports   计划与 CSV 报告目录
```

安装 Python 包后，可创建当前系统的图形启动器：

```bash
cloud-playlist-bridge install-launcher
```

- Linux 创建 `~/.local/share/applications/cloud-playlist-bridge.desktop`。
- Windows 在当前用户的“开始菜单\程序”目录创建 `Cloud Playlist Bridge.vbs`，并把
  状态保存在 `%LOCALAPPDATA%\Cloud Playlist Bridge`。
- macOS 创建 `~/Applications/Cloud Playlist Bridge.app`。

所有启动器都调用同一个本地 App，并把状态保存在对应平台的用户应用数据目录。移动或
重建虚拟环境后，需要再次执行 `install-launcher`。所有平台都保留 `app`、`plan` 和
`apply` 命令作为回退。

## 网易云来源 API 选择

Spotify 目标端始终使用官方 Web API 和 Authorization Code with PKCE。网易云提供两种
只读来源模式：

- 默认适配器读取网易云公开网页使用的接口，无需额外服务，但这些接口不是稳定的开放
  平台契约。
- 用户显式提供 `api-enhanced` 地址时，使用 `/playlist/detail` 和 `/song/detail`。
  `api-enhanced` 是第三方逆向服务，不是网易云官方 API；请在本机运行，不要把 Cookie
  发送给公共实例。

网易云开放平台当前没有可直接替代“按分享 ID 读取任意个人歌单”的通用公开接口，
因此本项目不会猜测开放平台凭据，也不会把 `api-enhanced` 描述为官方接口。

本地运行 `api-enhanced` 示例：

```bash
docker run --rm -p 127.0.0.1:3000:3000 moefurina/ncm-api:latest
```

## CLI 工作流

浏览器 App 不是必需项。`plan` 和 `apply` 可以直接在终端完成整个迁移流程，不会启动
本地 App 页面。以下命令显式调用虚拟环境解释器，因此不依赖 shell 激活状态或自动生成
的命令入口。

Linux 和 macOS：

```bash
./.venv/bin/python -m cloud_playlist_bridge plan 'https://music.163.com/playlist?id=123456789' --spotify-client-id YOUR_CLIENT_ID
./.venv/bin/python -m cloud_playlist_bridge apply reports/NAME.plan.json --spotify-client-id YOUR_CLIENT_ID --private
```

Windows 命令提示符或 PowerShell：

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge plan "https://music.163.com/playlist?id=123456789" --spotify-client-id YOUR_CLIENT_ID
.venv\Scripts\python.exe -m cloud_playlist_bridge apply reports\NAME.plan.json --spotify-client-id YOUR_CLIENT_ID --private
```

安装后，三个系统都可以用较短的 `cloud-playlist-bridge` 命令代替上述解释器前缀。首次
Spotify 授权仍会输出 OAuth URL，并通常会在默认浏览器中打开；这是身份验证，不是本地
App 页面。Spotify Developer 应用中仍须登记 loopback 回调地址。

生成或恢复匹配计划：

```bash
cloud-playlist-bridge plan \
  'https://music.163.com/playlist?id=123456789' \
  --spotify-client-id YOUR_CLIENT_ID
```

使用本地 `api-enhanced`：

```bash
cloud-playlist-bridge plan \
  'https://music.163.com/playlist?id=123456789' \
  --netease-api-base-url http://127.0.0.1:3000 \
  --spotify-client-id YOUR_CLIENT_ID
```

`plan` 会输出：

```text
<name>-<id>-<plan>.plan.json   带校验和的不可变执行计划
<name>-<id>-<plan>.csv         完整审计报告
<name>-<id>-<plan>.manual.csv  跳过歌曲和最多三个候选链接
```

执行固定计划：

```bash
cloud-playlist-bridge apply reports/NAME.plan.json \
  --spotify-client-id YOUR_CLIENT_ID \
  --private
```

可用 `SPOTIFY_CLIENT_ID` 和 `NETEASE_API_BASE_URL` 环境变量代替对应参数。Spotify
令牌默认保存在 `.state/spotify-token.json`；不要提交或分享该文件。

## 匹配策略与大歌单

评分权重为歌名 55%、歌手 25%、时长 15%、专辑 5%。live、remaster、伴奏、demo 等
版本不一致会受到惩罚。结果必须同时满足总分阈值、最低标题分和歧义差距，否则标记为
`ambiguous`、`low_confidence` 或 `not_found`，严格跳过并写入手动 CSV。

Spotify 搜索没有批量端点，因此每首唯一歌曲通常至少需要一次搜索。精确查询早停、
任务内查询缓存、有界重试和 SQLite 检查点会减少重复工作。普通 429 会遵守
`Retry-After`；配额耗尽时保留进度后停止。写入 10,000 首歌曲约需 100 个 Spotify
批次。

## 非目标与限制

- 不迁移音频文件、收藏时间、评论或播放历史。
- 基线不支持网易云私有或仅登录可见歌单。
- 跨平台元数据不能证明两个条目属于同一录音。
- App 不会自动接受低置信度结果，也不会在失败后删除部分创建的 Spotify 歌单。
- 真实 Spotify OAuth 和端到端写入需要用户凭据，离线测试无法完成该验证。

## 开发与验证

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

数据流、不变量、失败语义和验收标准见 [docs/architecture.md](docs/architecture.md)。

## 状态

当前版本为 0.5.0，支持 Linux、Windows 和 macOS 本地 App、CLI 规划与执行、网易云公开
歌单、可选的本机 `api-enhanced`、可恢复规划与写入，以及手动添加报告。Linux 已做运行
验证；Windows 和 macOS 启动器结构已经生成并测试，但当前环境没有对应实体主机，尚未
实际运行验证。
