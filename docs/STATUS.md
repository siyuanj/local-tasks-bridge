# Local trial status

## 2026-10-01 15:19 CST (Asia/Shanghai) - Mac 到 Google 的轮询延迟修复

- 用户反馈：Google Tasks 到 Mac 感觉较快，但提醒事项写回 Google 较慢。实测旧版
  最近 8 轮同步本身耗时 6～44 秒，并在每轮结束后固定再睡 60～61 秒，导致实际
  启动间隔为 66～104 秒；延迟来源是调度语义，不是单向接口不同。
- 本次修改：commit `eced2d4379b8dc043125ca8c948c9146741b0052` 将 60 秒定义为
  start-to-start 周期，从下一次等待中扣除本轮执行时间；超时轮次不再额外等待。
  Google 权限、My Tasks 范围、破坏性限额和写入确认逻辑均未改变。
- 自审与测试：检查正常轮次、超过 60 秒轮次、批量审批对话提前唤醒、并发锁和退出
  路径；新增 2 个调度回归，专项 2 项及全套 97 项通过，py_compile、shell 语法、
  release source gate、`git diff --check` 均通过。
- 现在真实状态：只读 release/current 已切至上述 commit，引擎 SHA-256 为
  `ae7dc600a2fb0e32112a0d165b68150a350615963eaabe1f0d643cef0b5da4ac`。
  新版本后台启动时间 15:17:59 与 15:18:59 CST，实测正好相隔 60 秒；第二轮
  15:19:07 完成，状态 `ok`、失败计数 0、错误为空、无待审批计划。LaunchAgent
  running，PID 69610；空闲时宿主和 Python 均为 0.0% CPU，RSS 合计约 66 MiB。
- 卡在哪：当前无阻塞。
- 还没验证的：未创建额外真实任务污染 My Tasks，因此尚未用新建任务逐秒测量端到端
  Mac→Google 延迟；按调度上界，通常应在下一分钟轮次处理，Google API/代理耗时另计。
  重启、长时间睡眠/断网和通用删除仍未真实验收。
- 要用户定的：无。

## 2026-10-01 11:14 CST (Asia/Shanghai) - 最新任务收敛与 10 条完成回写

- 用户要求：解决 Google 新任务没有及时出现在 Mac，以及此前因批量安全限额暂缓的
  “测试任务 1～10”完成回写。用户本次请求构成对这 10 条具体完成操作的明确批准；
  没有放宽以后批量删除或完成的自动审批。
- 执行前实测：阻塞计划先包含 3 条 `apple_reminders.create`、3 条映射回写和
  10 条 `google_tasks.complete`；后台先安全导入 3 条新任务后，待批准计划稳定为
  10 条完成，population=15。两次旧版本管理执行均在 Google PATCH 的 TLS 握手
  阶段遇到 `UNEXPECTED_EOF`，计划仍为 10 条，未发生部分完成。
- 修复：commit `2be5d0f85e6871665b31041cd2261b534cd6505f` 新增仅用于任务完成的
  确认式重试。PATCH 传输结果未知时先 GET 单条任务；已完成则接受结果，仍活动才
  重试。POST、DELETE 和普通 PATCH 继续不重试。自审覆盖幂等性、未知写入结果、
  404/410 原有处理和调用范围；新增 2 个回归，网络子集 4 项及全套 95 项通过，
  py_compile、shell 语法、release source gate、`git diff --check` 均通过。
- 部署与真实结果：只读 release/current 已切到上述 commit，引擎 SHA-256 为
  `fd3b74cb474d5b36a2b0814ca4f844892c6fef54872dc3eb68e6463112490066`。
  一次性指纹批准计划为 total=10/destructive=10；真实同步 `completed=10`、
  `deleted=0`，后台恢复。
- 现在真实状态：11:11:42 CST 双端独立读取为 Google 活动 5、Mac 活动 5，标题
  多重集合及哈希一致；Google 中测试任务完成 10、活动 0，Google 完成历史共 22，
  Mac 本清单完成 10。11:12 收敛 dry-run 为 total=0/destructive=0。11:13:39
  后台自动周期状态 `ok`、`consecutive_failures=0`、`last_error` 空、无待审批计划；
  LaunchAgent running，PID 64608。
- 证据：私有目录中的 `approval-20261001-110923.log`、
  `verification-20261001-111139.json`、`convergence-20261001-111206.log` 以及管理工具
  自动生成的批准前备份；均为本机 0600 文件，未纳入 Git。
- 卡在哪：当前任务无阻塞。
- 还没验证的：整机注销/重启后的启动、长期睡眠/断网恢复、通用删除仍未做真实验收；
  本次确认式重试只覆盖完成状态，不承诺其他写操作在不稳定网络下自动重试。
- 要用户定的：无。

## 2026-10-01 08:26 CST (Asia/Shanghai) - Production OAuth 与后台验收完成

- 用户决定：明确要求执行并统一完成 Production 与长期授权；此前公开说明页和
  延长授权有效期均已分别确认。10 条批量完成事项在执行前已明确排除，不把本次
  “全部统一”扩展为其批准。
- Google 实测：Audience 显示 In production。新 token 于 08:11 签发，文件 0600；
  scope 集合与旧 token 相同，为 Tasks + userinfo.email + openid，新 refresh token
  与旧值不同且存在，未返回 `refresh_token_expires_in`。独立强制刷新成功，
  Google Tasks API 检查为 ok。已关闭含回调信息的完成标签页。
- 账号绑定：新令牌首次运行被 fail-closed 保护拦下，没有写入/删除任务。通过官方
  userinfo 对比确认新旧 token 的 subject 指纹和邮箱完全一致；旧状态确实绑定旧
  refresh token。私密备份后只替换 `account_binding.google` 哈希，其他状态逐字段
  相同，task 映射前后均为 12。`--dry-run --no-delete-stale` 成功读取 Apple 2、
  Google list 1/tasks 2；没有重建或丢弃映射。
- 网络与修复：后台出现 4 次 TLS EOF，直接连接实测超时，现有本地系统代理
  `127.0.0.1:7897` 的 HTTP/SOCKS 探测均为 HTTP 200。LaunchAgent 已备份并加入
  HTTP_PROXY、HTTPS_PROXY、NO_PROXY。引擎 commit
  `4375a1d0a6353a202ac5eb33da67d237c2eb7b04` 只为 Tasks GET 增加最多 3 次有限
  重试；POST/PATCH/DELETE 遇到未知传输结果不重试。97 项测试、py_compile、
  shell 语法、release gate 和 diff check 通过。
- 部署：新只读 release 的引擎 SHA-256 为
  `5ff64d19c83d5953cbd0e40e4020130ee602e7a54f0681be796af841e4e4cfc6`，`current`
  已指向该 commit。首次 `mv` 因目标为目录符号链接，把临时链接放进旧 release，
  顶层 current 未变；确认精确目标后移除该临时链接，以 `ln -shfn` 完成切换并
  复核源码/运行哈希。
- 实际后台验收：PID 56594 running；08:23:05、08:24:33、08:25:53、08:27:08
  CST 四轮连续成功，`consecutive_failures=0`、`last_error` 为空。当前状态仍为
  `awaiting_mutation_approval`，仅暂缓 `google_tasks.complete=10`；其余同步运行。
- 私有 OAuth 备份目录权限为 0700，其中 token、状态、配置和日志文件统一为
  0600；未将任何凭据纳入 Git。
- 尚未验证：注销/重启后的启动、长期跨睡眠/断网恢复、通用删除。Production
  解除 Testing 七天限制，但不保证令牌永不过期；撤销或 Google 安全规则仍可令其
  失效。
- 要用户定的：长期授权无剩余决定；10 条完成是否回写 Google 仍是独立待答事项。

## 2026-10-01 08:10 CST (Asia/Shanghai) - Branding 完成，Production 待确认

- 用户明确同意发布 OAuth 说明页。网站 commit `975fe65` 已 push 到
  `siyuanj.github.io`；GitHub Pages 状态为 built、无构建错误，应用首页和隐私
  政策两个 URL 均通过实际 HTTP 内容核验。
- Google Branding 已填写这两个公开 URL 和授权域名 `siyuanj.github.io`，控制台
  显示 `Branding changes saved!`。Audience 的 `Publish app` 已由 disabled 变为
  可点击，状态仍为 Testing；尚未切换 Production。
- 下一步影响：Production 会把授权从测试用户/七天期限改为生产模式，并允许
  其他 Google 账号在取得本应用客户端/授权入口时自行授权自己的数据。它不会
  公开当前账号的待办；权限保持 Tasks + openid/email。之后还必须备份旧 token、
  重新授权并核验刷新和后台轮次。
- 阻塞：电脑操作政策要求对授权有效期的实质扩展在操作时取得具体确认。已到
  `Publish app` 的最终动作前，等待用户确认。
- 尚未验证：In production、新 refresh token、刷新请求及后台授权轮次。现有
  10 条批量完成仍为独立待确认事项。
- 要用户定的：是否现在执行 Production 切换并重新授予同样的 Tasks + 身份权限。

## 2026-10-01 08:06 CST (Asia/Shanghai) - 长期 OAuth 公开说明页待发布

- 用户要求：继续配置长期 Google 授权。Mac 已解锁，Google Auth Platform
  再次确认 Audience 为 External / Testing，Publish app 禁用并明确要求先完成
  Branding；Branding 中应用首页、隐私政策和授权域名为空。
- 已准备：在独立的网站工作副本 `../website-branding` 中新增应用首页和隐私
  政策，说明本地同步用途、Tasks + 身份权限、数据用途、本地存储、保留、撤销
  及 Google Limited Use。页面不含待办、邮箱、token、client secret 或私有日志；
  已提交为网站本地 commit `975fe65`，尚未 push，公开站点未改变。
- 验证：网站 `git diff --check` 通过；本机缺少仓库 Jekyll gems，
  `bundle exec jekyll build` 未运行成功且没有安装依赖。需要发布后核验 GitHub
  Pages 构建和两个 URL。
- 当前阻塞/下一步：公开学术网站属于对外发布，已将两个本地草稿作为具体可
  复核结果交给用户，等待是否发布的明确答复。批准后 push、核验 Pages、填写
  Branding，再到 Production / 新 OAuth 授权的操作时按接口规则取得具体确认。
- 尚未验证：Google Production、新 refresh token、长期刷新和后台授权轮次均未
  完成；现有同步范围、单次破坏性限额及 10 条待确认完成计划未改变。
- 要用户定的：是否将两页说明发布到 `siyuanj.github.io`。

## 2026-09-30 23:32 CST (Asia/Shanghai) - 长期 OAuth 配置准备及锁屏阻塞

- 用户要求：配置长期 Google 授权；沿用本人项目与现有 Tasks + 身份权限，不改变同步范围或破坏性限额。
- 本次操作：Google 控制台 Audience 实测 External / Testing；Publish app 禁用，提示先完成 Branding。将品牌名从 My Local Tasks Bridge 保存为 Local Tasks Bridge，页面显示 Branding changes saved；回到 Audience 后仍不能 Publish。支持/开发者邮箱已配置，应用首页/隐私政策/条款/授权域名为空；具体缺失门槛仍需进一步核查。
- 已准备：docs/09-30 long-term-oauth.md 记录官方要求、Production 下重新授权、私有 token 备份、刷新/API/后台验收流程。只读 GitHub API 确认本人 siyuanj.github.io 仓库和 Pages 已存在；未修改或发布网站。同步代码未变，无需重复此前通过的离线测试。
- 当前实测：launchctl print 显示服务 running、PID 50481；daily-status.json 最新 last_success_at=2026-09-30T15:30:45+00:00（23:30:45 CST）。仍保留 10 条批量完成的独立待确认事项，不将本次长期授权请求作为其批准。
- 阻塞：电脑接口返回 Mac 已锁屏且不能自动解锁，已请求用户手动解锁。未切换 Production，未停止服务、替换 token、扩展权限或发布公共页面。
- 未验证/下一步：解锁后核实具体 Branding 门槛；必要时准备本人站点说明页。最终延长授权有效期时，按电脑接口要求取得具体确认，再执行 Production 切换及新授权并核验实际后台轮次。长期有效期尚未验收，不能报告长期授权已完成。
- 要用户定的：手动解锁 Mac；最终扩展授权时的具体确认尚未到可执行步骤。

## 2026-09-30 23:17 CST (Asia/Shanghai) - 自动后台启动与原生权限宿主

- 用户请求/决定：询问自动同步如何启动，沿用本任务既有安装/同步授权；用户已手动允许 Local Tasks Bridge 的提醒事项权限。10 条已在 Mac 完成的测试任务是否批量回写 Google 的具体确认仍待答。
- 本次修改：新增 scripts/install-local-background.py、LocalBridgeLauncher.swift、scripts/package-local-launcher.py 及 docs/09-30 background-local.md，README 指向后台文档。安装器复制固定哈希的同步代码到 releases/<commit>，current 指向该版本，轻量 Python 3.12/stdlib 为 58M，排除第三方 site-packages；不再依赖 Codex 缓存或工作目录。既有 daily-config/state/token 留在私有目录，配置改路径前已备份。
- 部署来源：同步引擎/Swift helpers 为 clean commit bb14a8f6744fcd8200cae26810cbd5a8cc6b70a0（引擎仍含 6629846 的已验收修复），原生宿主源码为 2d4faea1c0b4f99aaed742eb4a79bc3796e78e6f。使用原有 source gate 明确支持的 non-main/unpushed override，记录个人已审查补丁/不向上游发布的理由；未允许 dirty 或替换 origin，未 push。
- 自审与修复：核查部署清单/路径/私有模式/哈希、无新增 Google scope、原生宿主进程退出/信号/子进程参数。首次 Python 复制因 pkgconfig 的缺失开发符号链接失败，配置与 LaunchAgent 尚未写入；保留不完整目录，修复忽略 pkgconfig 后成功。首次 GitHub 查询未走系统代理而卡住，结束该查询；后续沿用已存在的本地代理进行只读核验成功。
- 实际系统障碍：直接 Python LaunchAgent 的 Swift EventKit 访问被拒，系统设置仅 ChatGPT 可读 Reminders。已停止该进程，再以实测 116K 原生 App 为权限宿主。使用现有 CLT 编译、ad-hoc 签名和严格签名检查，无完整 Xcode 下载。工具禁止操作 UserNotificationCenter，用户自行允许；随后系统设置 AX 确认 Local Tasks Bridge 与 python3.12 都为 on，ChatGPT 仍 on。
- 本次验证：语法/Swift 类型检查、运行代码 SHA-256、plist lint、原生 App codesign --verify --strict、日志目录 0700/文件 0600。launchd 已加载并 running；真实定时轮次 23:12:28→23:12:41、23:13:41→23:13:52 正常完成（当前有批量完成暂缓，其他同步正常）；停止后旧 PID 50389/50397 均退出，重新启动 PID 50481，23:14:56→23:15:08 再完成一轮。每轮实际读取 2 条活动 My Tasks 并通过 2 条 title/due Google 核验，completed/deleted 均为 0。
- 当前真实状态：LaunchAgent com.icloud-reminders-google-sync 的 ProgramArguments 为 ~/Applications/Local Tasks Bridge.app/Contents/MacOS/LocalBridgeLauncher；RunAtLoad/KeepAlive 开启，轮次完成后等待 60 秒。状态 awaiting_mutation_approval，原因明确为 Google Tasks complete=10 超过单次限额 1；这 10 条未被自动完成/删除。没有改动同步引擎，此前 95 项离线测试未重复跑。
- 证据：audit/background-install.log（首次失败）、background-install-retry.log、background-native-package.log；私有 background-preflight.log、launcher-provenance.json、原配置/agent 备份；后台日志 ~/Library/Logs/icloud-reminders-google-sync/ 与私有 daily-status.json。启动/停止及回滚见 docs/09-30 background-local.md。
- 未验证/下一步：整机重启/注销后自启动尚未实际执行；睡眠恢复与断网长测未做；Google External/Testing 约 7 天授权限制仍未处理；通用删除未验收。批量完成需要用户对具体 10 条的答复，不能代批准。待答后核验精确计划并执行，再确认 Google 与 Mac 状态一致。
- 要用户定的：已发出“测试任务 1～10 回写完成”具体确认，未获得答复；原生 App 权限问题已由用户解决。


## 2026-09-30 22:54 CST (Asia/Shanghai) - 用户确认日常组件已切换

- 用户反馈：已将桌面组件清单切换为 My Tasks；此项依据用户确认，未再次使用不可靠的桌面编辑器自动化验证。
- 已有实测：Google 与 Mac 均有 12 条未完成事项且标题匹配；测试 C 从桌面完成后已回写 Google，completed=1、deleted=0。详见上一节。
- 当前限制：未安装后台同步，后续变更需手动运行；Google Testing 授权期限、持久运行部署仍未处理。日常原有已完成历史仍保留在 Google，首次没有迁入 Mac。
- 下一步：若继续完成自动日常使用，需准备持久运行方式并处理 Testing 授权期限，验证后台执行与退出方式；当前没有常驻服务可声称已启用。
- 要用户定的：无当前待答问题。


## 2026-09-30 22:53 CST (Asia/Shanghai) - 桌面完成回写通过，My Tasks 首次接入

- 用户决定：已在桌面勾选 C；选择日常同步现有 My Tasks。并询问组件是否隐藏完成项，已说明完成后退出组件但保留记录。
- 本次真实验收：测试清单活动项 0；dry-run 计划 1 项完成，真实运行 completed=1、deleted=0；Google API 确认 A/B/C 全部 completed，原生 UI 也显示 3 项完成。复核计划 total=0。最后一条桌面完成的真实回归通过。
- 日常接入：通过原生 UI 在 iCloud 新建 My Tasks；私有 daily-config.json 使用独立 daily-state/status、复用本人 OAuth、只选择 My Tasks、禁止创建新 Google 清单。首次同步禁用完成/删除传播，导入 12 条未完成项，google_applied=12，Google inserted/updated/completed/deleted 均为 0；对已有 Google 记录附加同步元数据。初始快照 11 条活动项，期间 Google 新增 1 条，已重新读取并纳入 12 条核验。
- 核验：导入前后 Google 已有任务 ID、完成状态、删除状态全部保留；Google 与 EventKit 的 12 条活动标题多重集合相同，原生 UI 侧栏显示 My Tasks 12。已有 12 条 Google 完成历史未导入 Mac。随后启用已验证的完成传播，单次破坏性限额仍为 1，空活动清单防删与冲突跳过保留；dry-run total=0。此设置也允许限额内删除传播，通用删除未做真实验收。
- 变更与自审：本次无同步代码修改，无必要重复此前 95 项离线测试；更新验收文档及状态。私有配置和快照均在 ~/.config/reminders-task-bridge-trial，未纳入 Git。
- 证据：widget-complete-dry/live/converged.log、daily-first-dry/live.log、daily-converged.log、daily-google-before-latest/after.json、daily-apple-after.json（全部私有目录）。测试使用源码 6629846，当前仅文档更新。
- 阻塞/下一步：已请用户把桌面组件列表切换为 My Tasks；原生组件配置窗口自动化不可靠。后台同步尚未安装，当前仍是手动同步；长期 OAuth（Testing 7 天）和日常后台运行待后续处理。
- 尚未验证：My Tasks 在桌面组件实际显示、Gemini 本次直接创建任务、重复任务/子任务/精确时间、长期后台可靠性。
- 要用户定的：无新增权限；只需完成桌面组件列表切换。


## 2026-09-30 22:48 CST (Asia/Shanghai) - 桌面组件实际显示已确认

- 用户操作与证据：用户已将原生提醒事项桌面组件切换至 Bridge Test 2026-09-30，截图显示 1 条未完成的 Bridge test C；截图保存在任务目录 audit/widget-visible-user.png。桌面显示已验证，不再仅为注册/编辑器元数据。
- 本次核验：Google API 读取测试清单，A/B 为 completed，C 为 needsAction；未对日常清单作写入。源码为 6629846，本次未修改同步逻辑或重复运行此前通过的 95 项离线测试。
- 阻塞及下一步：桌面自动化仍定位到错误的组件配置窗口，点击“完成”无状态变化；已请用户手动点击桌面 C 左侧圆圈。收到后执行计划检查及真实单次同步，再核验云端 C completed 且无删除。
- 未验证：桌面勾选回写、最后一条完成的真实回归、日常清单、后台自动同步和长期 OAuth 均尚未验收。
- 要用户定的：无新增权限请求；仅需要执行上述桌面勾选操作。


## 2026-09-30 21:15 CST (Asia/Shanghai) - 小组件添加尝试与最后一条完成保护

- 用户操作：已打开小组件编辑器。现场 AX 确认提醒事项类别存在，且选择“此 Mac 上”；尝试点击中号预览和完成后，接口仅返回原有照片小组件，不能确认已添加。已请用户手动添加提醒事项并选择测试清单。
- 本次修改：为最后一条完成新增回归；确认原代码因活动清单为空而不回写。同步计划和执行拆分 allow_completions / allow_deletes；明确完成记录可回写，缺失条目/重复项仍受空清单防删保护，显式禁用传播仍不回写完成。
- 自审与实测：检查计划/执行条件一致性、清单策略、破坏性限额及显式禁用覆盖；修复前回归因 completion patch 调用 0 次失败，修复后隔离断网全套 95 项通过，含缺失条目不删除和禁用传播不写入的子案例；git diff --check 通过。
- 当前真实状态：本次只运行真实 dry-run，total=0；C 仍未完成，A/B 已完成。未写新真实任务状态、未接入 My Tasks、未启用后台同步。
- 未验证与下一步：待用户确认桌面可见测试清单，再从桌面完成 C 并验证“最后一条”云端回写；原生日常组件、长期授权、自动后台行为仍未验收。
- 证据：audit/last-completion-before.log、after.log，私有 widget-preflight.log；源码 docs/09-30 local-acceptance.md。
- 要用户定的：无新的权限请求；需用户完成桌面组件放置/列表选择这一接口无法可靠执行的操作。


## 2026-09-30 21:03 CST (Asia/Shanghai) - 桥接真实双向试验与完成后误删修复

- 用户决定：已分别同意 Google 数据政策、创建 Desktop OAuth 凭据、授予 Google Tasks 读写权限；表示前次遗漏勾选为误操作。
- 已完成：个人项目 Tasks API 启用；测试用户仅本人；credentials/token 均在 ~/.config/reminders-task-bridge-trial，文件 0600。实际 scope 为 Tasks + userinfo.email + openid，无 Calendar/Cloud Platform。未启用账单或 LaunchAgent。
- 本次实测：iCloud 新建 Bridge Test 2026-09-30；Mac→Google 新建、改名、完成，Google→Mac 新建、改名均通过 API/原生 UI 验证。Google→Mac 完成暴露上游误删测试 B：活动清单刷新后，已完成清单仍为旧快照，导致云端 B 被删；只影响隔离测试数据。
- 修复与自审：icloud_reminders_google_sync.py 在入站修改后同步刷新已完成快照；test_local_safety.py 新增实际编排回归。修复前测试明确检测到一次 delete_task；修复后隔离断网 94 项测试通过。新增 trial_acceptance.py 仅限该清单的可复核 API 验收探针。
- 修复后真实复测：重新激活并重建测试 B 后，再从 Google 完成；Mac UI 和 Google API 都保留 B 的已完成状态，deleted=0。随后一轮 total=0，无新增、更新、完成、删除，unchanged=1。当前 A/B 完成，C 未完成。
- 证据：docs/09-30 local-acceptance.md（源码仓库）；audit/completion-regression-before.log 与 after.log；私有 sync-google-complete-fixed.log 与 sync-idempotence.log。此前 Google B 已删除，复测重建为新 ID，未掩盖该失败。
- 阻塞：桌面/通知中心原生自动化返回 illegalArgument、windowNotFoundAtPosition/noWindowsAvailable；已请用户打开“编辑小组件”，尚无答复。未添加/验证桌面提醒事项组件。
- 未验证：日常 My Tasks 未接入；后台自动同步未启用；最后一条完成时的空清单保护、通用删除/恢复、重复任务、子任务与精确提醒时间未验证。Testing 授权 7 天过期，长期配置待验收后处理。
- 要用户定的：目前只需打开小组件编辑界面并告知；没有新的权限请求。


## 2026-09-30 20:45 CST (Asia/Shanghai) - Google 本地桥接 OAuth 配置

- 用户决定：同意此前明确展示的 Google User Data Policy；并表示授权直接推进本任务。
- 本次观测：已在 Google 官方控制台提交政策与品牌配置，页面确认 “OAuth configuration created!”。桌面客户端表单已选择 Desktop app，名称 Mac Reminders Local Bridge。
- 当前边界：尚未点击创建客户端，未获得 credentials/token，未读取或写入真实待办。电脑 UI 工具要求在创建安全凭据时具体确认，已发送相应问题，等待答复。
- 下一步：创建并私密保存个人 OAuth 凭据、启用 Tasks API，完成实际授权后按原计划验证单清单双向同步和桌面小组件。
- 尚未验证：账号/API 授权、EventKit 运行、云端写入、组件显示及后台稳定性。之前 93 项测试是源码级结果，本次未重复运行。
- 已核对的维护限制：Google 官方 OAuth 文档规定 External/Testing 状态刷新令牌 7 天过期；长期配置留待首次回环成功后处理。来源：https://developers.google.com/identity/protocols/oauth2
- 要用户定的：当前具体客户端凭据创建确认；其他常规准备继续按既有授权推进。


## 2026-09-30 Asia/Shanghai — reviewed manual trial

- User request: try Apple Reminders/Google Tasks synchronization, keep Google Tasks, avoid a full Xcode installation, and check that data is not sent to the repository author.
- Base: upstream 3501800b672ef58c823eb0711c22412c2db98dce. Work branch codex/local-safe-trial. The installer and persistent LaunchAgent have not run.
- Changes: OAuth requests only the selected service plus openid/email; manual OAuth URL handoff; RemindersApply accepts the same list allowlist as the exporter. Added offline regression checks.
- Review: inspected imports, network destinations, subprocess calls, token files, read/write helper paths, list filtering and installer side effects. Observed destinations are Google API/OAuth endpoints; no developer telemetry or remote-control endpoint was found in inspected paths. This is not a malware-free guarantee or a full formal audit.
- Validation: baseline 91 tests and patched 93 tests pass in a macOS sandbox denying network and other user-file data reads. First sandbox run reported 4 failures due to denied test lock location and parent metadata access; after isolated XDG_CONFIG_HOME and permitted metadata, the suite passed. Network and private-file denial probes passed. Shell syntax and release-gate self-tests pass. Both Swift helpers typecheck using the existing CLT SDK explicitly; no EventKit data access was executed. Existing nonoptional nil-coalescing warning in RemindersApply remains.
- Live setup: private config is outside the repository at ~/.config/reminders-task-bridge-trial/config.json (0600, parent 0700); only Bridge Test 2026-09-30 selected, no ADC fallback, no auto-login/UI notifications, no deletion propagation or scheduled process. No credential/token has been acquired.
- Google Cloud: independent reminders-tasks-local-bridge project created in the user's account; OAuth branding draft My Local Tasks Bridge is at the User Data Policy agreement step. No billing enrollment, API key reuse or third-party account.
- Pending: user agreement to Google's policy; OAuth desktop client/API setup; Google and Reminders consent; single-list dry-run then create/edit/complete round trip and widget rendering. No production deployment or synchronization is claimed.
- Source-only results do not establish native permissions, actual cloud writes, background reliability or visible widget behavior.
