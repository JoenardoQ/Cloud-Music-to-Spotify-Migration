# Architecture contract

## Outcome and users

面向希望把自己可访问的网易云歌单迁到 Spotify 的个人用户。成功意味着：源歌单
顺序被保留；每个源条目都有可审计结果；只有高置信度结果可自动写入；写操作必须
由用户显式授权。

## Boundaries

```text
local SPA / standalone CLI -> NetEase read adapter -> source models
                           -> SQLite job/checkpoint + Spotify search cache
                           -> staged search -> deterministic Matcher
                           -> checksummed immutable plan + CSV + manual CSV
explicit apply action      -> verified plan -> execution journal
                           -> Spotify playlist writer -> resumable batches
```

- `netease.py` 只读取网易云公开元数据，负责数量与字段完整性。默认适配网易云网页
  只读接口；配置 `NETEASE_API_BASE_URL` 或 CLI 参数后，改用用户自建的
  `api-enhanced` `/playlist/detail` 与 `/song/detail` HTTP API。两种方式共享相同的
  完整性校验和领域模型。
- `spotify.py` 负责 PKCE、令牌刷新、HTTP 重试、搜索和歌单写入。
- `matching.py` 是无网络的确定性算法，可单元测试。
- `jobs.py` 持有规划检查点和即时迁移所需的查询缓存。
- `plans.py` 是计划序列化、完整性校验、报告和手动名单的唯一所有者。
- `execution.py` 持有外部写入日志、批次恢复和不确定状态协调。
- `migration.py` 编排分级搜索，不隐藏配额或源数据失败。
- `cli.py` 只处理输入和面向人的输出，不包含业务算法。Linux、Windows 和 macOS 都可
  通过安装后的命令入口或 `python -m cloud_playlist_bridge` 直接执行 `plan/apply`，无需
  启动 App 前端。
- `app.py` 是仅监听回环地址的本地 HTTP 编排层；它在后台线程调用现有服务，并向单页
  前端提供增量状态，不复制匹配或写入算法。
- `web/` 是无外部资源的单页前端。左右歌曲列表采用窗口化渲染，避免为 10,000 首歌曲
  同时创建 DOM 节点。
- `launchers.py` 根据运行平台生成 Linux `.desktop`、Windows 开始菜单 `.vbs` 或
  macOS `.app` 启动器；三者调用同一个 Python 模块和浏览器 UI，不分叉迁移逻辑。
  Windows 启动器通过系统自带 Windows Script Host 隐藏控制台窗口，状态与报告写入
  当前用户的 `%LOCALAPPDATA%`。其他系统仍可直接使用 CLI。
- 所有模块均为普通 Python 代码，不调用或依赖 Agent、插件或 Codex 运行时。

## Data flow and invariants

1. 从输入提取纯数字歌单 ID。
2. 请求歌单详情；`trackIds` 是顺序真源，不能用只含前若干首的 `tracks`。
3. 每批请求歌曲详情，以歌曲 ID 建索引后按 `trackIds` 重排。
4. `trackCount`、`trackIds` 和 `--expected-count` 的冲突会中止，缺失详情会在源
   歌单模型中记录并使计划失败，禁止静默迁移残缺歌单。
5. 搜索结果与匹配结果逐首提交到任务 SQLite；同一源快照才可恢复。缓存只服务于
   这次迁移，不构建长期 Spotify 内容库。
6. 每首歌先执行精确查询。达到自动匹配条件时早停；否则才执行后备查询。相同查询
   从任务缓存读取。
7. 完成的计划具有 schema 版本、计划 ID、源摘要、策略参数与 SHA-256 完整性校验。
   `apply` 只接受通过校验的计划，且绝不重新搜索。
8. 只有 `matched` URI 会按源顺序写入；其余状态严格跳过并进入 `manual.csv`，其中
   包含源信息、拒绝原因和最多三个 Spotify 候选链接。
9. 每 100 首为一个写入批次。发送前原子记录 inflight，确认响应后记录已完成数量和
   snapshot ID。异常退出后可协调不确定批次并恢复，不自动创建第二个歌单。

## Matching contract

匹配器使用 Unicode NFKC、大小写折叠、空白/标点归一化，并识别常见版本标记。
评分由标题、完整歌手集合、时长和专辑构成。版本标签必须按完整词或明确中文标签
识别，不能用任意子串。必须同时满足最低总分、最低标题分和歧义差距；否则状态为
`low_confidence` 或 `ambiguous`。算法不使用机器学习，也不把 Spotify 内容用于
模型训练。

## Security and privacy

- 桌面 CLI 使用 Authorization Code with PKCE；不收集 client secret。
- 请求 `playlist-modify-public`、`playlist-modify-private` 和恢复私有歌单所需的
  `playlist-read-private`。
- OAuth state 必须校验；回调仅监听显式 loopback 地址。
- token 文件写入后尽力设置为当前用户可读写，并由 `.gitignore` 排除。
- 日志和报告不包含 access token、refresh token 或网易云 cookie。
- App 默认只监听 `127.0.0.1`，拒绝非回环绑定；所有变更请求要求进程启动时生成的
  CSRF token。Spotify token 不进入浏览器状态或日志。
- 不接受远程公共 `api-enhanced` 作为隐式默认值；服务地址由用户显式提供，文档示例
  仅绑定 `127.0.0.1`。第三方服务的安装、更新和 Cookie 管理由用户负责。

## Failure semantics

- 输入错误：退出码 2，未产生外部写入。
- 网络、字段变化、鉴权或限流耗尽：退出码 1，显示具体阶段。
- 配额耗尽：退出码 1，任务已持久化；重复同一 `plan` 命令恢复。
- 匹配不到不是程序错误：写入报告并继续；但零匹配时禁止执行空迁移。
- Spotify 歌单已创建后的失败：退出码 1，执行日志为 `partial` 或 `uncertain`；重复
  `apply` 协调后继续。无法安全判断远程状态时拒绝猜测并给出确切恢复条件。

## Acceptance criteria

- URL/ID 解析、顺序回填、评分、歧义拒绝、缓存、检查点和分批恢复均有离线测试。
- `plan` 不创建或修改 Spotify 歌单；`apply` 不重新搜索。
- Spotify 写入使用当前 `POST /me/playlists` 和 `/playlists/{id}/items`，单批不超过
  100 项。
- 任意源歌曲缺失详情时默认不执行迁移；用户明确选择残缺迁移后，缺失项保留原位置并
  进入手动报告，且绝不发送到 Spotify 搜索或写入。
- 计划校验和可检测任何执行相关字段篡改。
- CSV 报告包含每个源索引、源信息、状态、分项评分、前三候选和原因。
- `manual.csv` 只包含被跳过歌曲，足以支持用户在 Spotify 中手动添加。
- 10,000 首模拟任务可完成；中断恢复不重做已保存搜索。
- 同一秒或并行报告不覆盖；报告与执行日志采用原子替换。
- 所有凭据路径均默认被版本控制忽略。
- 单页 App 能加载源歌单、增量显示匹配结果与日志、显示规划/写入进度，并且只有用户
  点击确认写入后才调用 Spotify 创建接口。
- Linux、Windows 和 macOS 启动器都固定使用安装时的 Python 解释器，并把状态写入
  对应平台的用户应用数据目录；移动虚拟环境后必须重新安装启动器。
- Linux、Windows 和 macOS 都能通过模块入口执行 `plan` 和 `apply`；CLI 不依赖本地
  App 页面，并保持“先生成不可变计划、再明确执行写入”的两阶段边界。
