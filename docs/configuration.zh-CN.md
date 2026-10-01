# 配置与命令行参考

[English](configuration.md) · **简体中文**

大多数人用不到这一页：设置向导和 App 中的“设置”已经涵盖了日常需要的选项。本页是设置文件、按列表的同步策略、代理、同步间隔以及所有 `ltb` 命令的参考资料。

App 与同步引擎之间的技术接口规定在 [app-engine-contract.md](app-engine-contract.md)（英文）中。

## 文件位置

| 路径 | 内容 | 权限 |
| --- | --- | --- |
| `~/.config/local-tasks-bridge/` | 设置与私密数据文件夹 | `0700`（仅你本人） |
| `…/config.json` | 设置（即本页内容） | `0600` |
| `…/credentials.json` | 你自己的 Google OAuth 客户端（如果导入过） | `0600` |
| `…/token.json` | Google 登录信息（OAuth 令牌） | `0600` |
| `…/state.json` | 同步对应关系：哪条提醒事项对应哪个 Google 任务、更改指纹、账号绑定的哈希值，以及条目标题 | `0600` |
| `…/status.json` | 上一轮的结果、数量和哈希值——绝不包含标题 | `0600` |
| `…/paused` | 暂停同步期间存在 | `0600` |
| `…/sync-now` | 被“触碰”时请求立即同步一轮 | `0600` |
| `…/backups/` | 执行有风险的操作前自动生成的私密备份 | `0700` |
| `~/Library/Logs/LocalTasksBridge/engine.log` | 引擎日志，**包含任务标题** | `0600`，文件夹 `0700` |
| `~/Library/Logs/LocalTasksBridge/app.log` | App 与 launchd 的输出 | `0600` |
| `~/Library/LaunchAgents/io.github.siyuanj.local-tasks-bridge.plist` | 登录时启动 App 的登录项 | `0644` |
| `~/Applications/Local Tasks Bridge.app` | App 本身（默认位置；放在 `/Applications` 也可以） | |
| `~/.local/bin/ltb` | 指向 App 内 `ltb` 命令的链接（可选） | 链接 |

切勿把 `credentials.json`、`token.json`、`state.json` 或日志分享给他人。

## 修改设置

- **在 App 中：** 打开菜单中的“设置…”，其中有“通用”“列表”“安全”“Google”“网络”和“高级”几个标签页。点按“应用”后修改生效。
- **在命令行中：**

  ```bash
  ltb config show                                    # 查看当前面向用户的设置
  echo '{"sync_interval_seconds": 300}' | ltb config merge --json
  ```

  `config merge` 从标准输入读取一个 JSON 对象，校验合并后的完整结果，以 `0600` 权限原子写入，并输出新的设置。未知的键或无效的值会以 `config_invalid` 拒绝，不会写入任何内容。
- **手动编辑：** 你也可以用文本编辑器修改 `config.json`，这也是修改[高级选项](#高级选项)的唯一方式。请先备份，保持 JSON 格式正确，改完后退出并重新打开 App，让后台同步重新读取文件。文件无效时同步会停止，直到修复为止。

`ltb config init` 会在 `config.json` 不存在时写入产品默认设置；`ltb config init --force` 会先备份再替换已有文件。

## 设置项参考

下表中的键就是 `ltb config show` 显示、`ltb config merge` 接受的那些。“默认值”是设置向导和 `config init` 写入的值。如果文件中缺少某个键，引擎会改用最后一列中的值，而这个值有时更保守——请保留设置向导写入的键。

| 键 | 取值 | 默认值 | 含义 | 缺失时 |
| --- | --- | --- | --- | --- |
| `include_lists` | 提醒事项列表名称的数组 | 你的选择 | 要同步的提醒事项列表，名称必须完全一致。**空数组表示所有提醒事项列表。** 移除某个列表只会停止同步它，不会删除任何内容。 | `[]` |
| `list_policies` | 对象 | `{}` | 按列表覆盖全局设置，见[下文](#按列表的同步策略) | `{}` |
| `bidirectional` | `true` / `false` | `true` | 没有单独设置 `direction` 的列表是否双向同步；`false` 表示只从提醒事项同步到 Google | `false` |
| `delete_stale` | `true` / `false` | `true` | 把完成和删除同步到另一边（也是各列表 `delete_propagation` 的默认值） | `true` |
| `conflict_policy` | `newer_wins` / `skip` | `newer_wins` | 同一条目在两边都被修改时怎么办，见[冲突](#冲突) | `newer_wins` |
| `tasks_sync_undated` | `true` / `false` | `true` | 是否同步没有截止日期的提醒事项和任务 | `false` |
| `tasks_import_unsynced` | `true` / `false` | `true` | 导入尚未与提醒事项关联（没有同步标记）的 Google 任务，见[导入已有的 Google 任务](#导入已有的-google-任务) | `false` |
| `tasks_create_missing_lists` | `true` / `false` | `true` | 选中的提醒事项列表在 Google 中没有同名列表时，自动创建；设为 `false` 时，这种情况会让本轮同步报错停止 | `true` |
| `tasks_complete_stale` | `true` / `false` | `true` | 你完成一条提醒事项时，把对应的 Google 任务也标为完成。设为 `false` 时，已完成的提醒事项会被当作已移除，于是对应的 Google 任务会被**删除**（在同步删除的前提下） | `true` |
| `sync_interval_seconds` | 不小于 60 的整数 | `60` | 从一轮定时同步开始到下一轮开始的秒数。使用共享客户端时，无论这里怎么设置，引擎都至少等待 300 秒（5 分钟） | `900` |
| `trigger_min_interval_seconds` | 不小于 0 的整数 | 不写入 | 一轮同步开始后，因提醒事项改动、“立即同步”或 `ltb sync-now` 触发额外一轮之前至少要间隔的秒数；使用共享客户端时至少为 30 | `10` |
| `max_destructive_changes` | 不小于 0 的整数 | `25` | 计划中删除与完成的总数**超过**这个数时需要你确认；`0` 表示每一个都要确认 | `25` |
| `max_destructive_ratio` | 0–1 之间的数 | `0.25` | 删除与完成占所管理条目的比例**超过**这个值时需要确认；`1` 表示不检查比例 | `0.25` |
| `mutation_approval_prompt` | `true` / `false` | `true` | 主动询问被暂缓的更改——在 App 的“查看待确认的更改”窗口中，或在没有 App 运行引擎时用对话框询问；设为 `false` 时只发通知，你可以通过“查看待确认的更改…”或 `ltb approvals` 审核 | `true` |
| `macos_notifications` | `true` / `false` | `true` | 出现问题或有更改被暂缓时显示 macOS 通知 | `true` |
| `language` | `auto` / `en` / `zh` | `auto` | 引擎消息、通知和 `ltb` 输出的语言；`auto` 跟随 macOS | `auto` |
| `proxy` | `""` / `"none"` / `"http://主机:端口"` | `""` | 如何连接 Google，见[代理](#代理) | `""` |
| `oauth_client` | `auto` / `custom` / `bundled` | `auto` | 使用哪个 Google 客户端登录：`custom` 为你自己的（`credentials.json`），`bundled` 为共享客户端，`auto` 表示导入过自己的就用自己的，否则用共享的 | `auto` |
| `setup_completed_at` | 时间戳或 `null` | 由设置向导写入 | 完成设置的时间；`ltb status` 中显示为 `setup_completed` | — |

`config_version`（目前为 `2`）由设置向导写入，用于标识文件格式。

### 冲突

冲突是指同一条目在两轮同步之间、在两边都被修改了。

- `newer_wins`（默认）：最近修改的一方整体胜出——标题、备注、日期和完成状态都以它为准。有一个特例用于保护你的日期：如果较新的 Google 改动没有截止日期，而提醒事项中刚刚添加了日期，这个日期会被保留。
- `skip`：这一条在两边都保持不动，并且本轮同步会被报告为失败（“Bidirectional conflicts left Apple Reminders and Google Tasks unsynced”），直到你在任意一边修改让两边一致，或改用 `newer_wins`。其他条目仍会正常同步，并且同步对应关系会先被保存。

单向同步的列表不存在冲突：始终以源头一方为准。

### 导入已有的 Google 任务

开启 `tasks_import_unsynced` 后，对于“从 Google 同步到 Mac”的列表中没有同步标记的 Google 任务：

- 如果配对的提醒事项列表中有一条标题和截止日期都相同的未完成提醒事项，两者会被关联，并在 Google 任务中添加同步标记。
- 否则，会在配对的提醒事项列表中新建一条提醒事项，并给这个 Google 任务加上同步标记。
- 已完成的 Google 任务不会被导入，免得 Google 的历史记录塞满“提醒事项”。没有截止日期的任务，只有在该列表同步无日期条目时才会导入。

## 按列表的同步策略

`list_policies` 可以为单个列表覆盖全局选项。键是提醒事项列表的名称，必须与“提醒事项”中显示的完全一致；没写的字段继承全局设置。

```json
{
  "bidirectional": true,
  "delete_stale": true,
  "tasks_sync_undated": true,
  "conflict_policy": "newer_wins",
  "list_policies": {
    "工作": {
      "direction": "bidirectional",
      "delete_propagation": true,
      "sync_undated": true,
      "conflict_policy": "newer_wins"
    },
    "归档": {
      "direction": "apple_to_google",
      "delete_propagation": false,
      "sync_undated": false
    },
    "My Tasks": {
      "direction": "google_to_apple",
      "conflict_policy": "skip"
    }
  }
}
```

| 字段 | 取值 | 继承自 | 含义 |
| --- | --- | --- | --- |
| `direction` | `bidirectional`、`apple_to_google`、`google_to_apple` | `bidirectional`（`true` → `bidirectional`，`false` → `apple_to_google`） | 改动的流向。单向列表以源头一方为准。 |
| `delete_propagation` | `true` / `false` | `delete_stale` | 是否在该列表的同步方向上同步完成和删除。清理重复的 Google 任务也遵循这个设置。 |
| `sync_undated` | `true` / `false` | `tasks_sync_undated` | 是否包含没有截止日期的条目：导出无日期的提醒事项、导入无日期的 Google 任务。 |
| `conflict_policy` | `newer_wins`、`skip` | `conflict_policy` | 只对 `bidirectional` 列表有意义。 |

规则：

- 列在这里的列表，也必须出现在 `include_lists` 中才会被同步。
- 未知的字段、未知的取值，以及写成字符串的布尔值（如 `"true"`）都属于配置错误：引擎会在登录或写入任何内容之前停止。
- `google_to_apple` 列表如果在 Google 中不存在，会被跳过，而不会去创建一个空的 Google 列表。
- `ltb sync --no-delete-stale` 会对所有列表关闭完成与删除的同步，不论 `delete_propagation` 怎么设置。

## 高级选项

引擎能识别的键比 `config merge` 接受的更多。只有特殊情况才需要它们；请手动编辑 `config.json`（见[修改设置](#修改设置)）。括号中是默认值。

**安全与确认**

- `destructive_approval_ttl_seconds`（`600`，最小 `60`）——点按“执行”后，这次确认保持有效的时长。
- `mutation_approval_prompt_repeat_seconds`（`21600`，即 6 小时，最小 `600`）——选择“暂缓”后，多久之后再次询问。
- `auto_approve_destructive_loops`（`0`）——大于 0 时，被暂缓的计划连续出现这么多轮后会自动执行。请保持为 `0`，它只用于无人值守的测试环境。
- `allow_empty_source_delete`（`false`）——即使所有选中的提醒事项列表都读出为空，也允许删除。请保持关闭：读出空结果，更常见的原因是提醒事项或 iCloud 的临时故障，而不是你真的清空了列表。
- `verify_title_due_after_sync`（`true`）、`verify_title_due_retry_attempts`（`3`）、`verify_title_due_retry_delay_seconds`（`2.0`）——写入后重新读取 Google，逐条核对标题和截止日期；重试后仍不一致则本轮失败。

**同步范围**

- `lookahead_days`（`365`）——只用于继承自上游的 Google 日历模式。在 Google Tasks 模式下，所有有截止日期的提醒事项都会同步，无论多久以后到期。
- `tasks_mirror_lists`（`true`）——按名称配对列表。设为 `false` 时，所有选中的列表都会汇入同一个 Google 列表（`tasks_list_id` 或 `tasks_list_title`，否则为第一个 Google 列表）；App 不支持这种继承自上游的模式。
- `tasks_mirror_empty_lists`（`true`）——即使提醒事项列表为空，也为它配对或创建 Google 列表。

**登录**

- `manual_oauth_browser`（`false`）——不自动打开浏览器，而是打印登录网址（等同于 `ltb auth --no-browser`）。
- `auto_reauth_browser`（`false`），以及 `auto_reauth_min_interval_seconds`（`21600`）、`auto_reauth_timeout_seconds`（`300`）、`auto_reauth_timeout_retry_interval_seconds`（`300`）——登录过期时，让后台引擎自行打开浏览器登录，失败后按指数退避重试。产品中默认关闭：由 App 来提示你。
- `use_adc`、`adc_credentials_path`——通过 gcloud 的应用默认凭据（Application Default Credentials）登录（`ltb gcloud-login`）。这是上游遗留的方式，App 不支持。

**通知**

- `notify_success_min_interval_seconds`（`3600`）和 `notify_failure_min_interval_seconds`（`300`）——“已同步”和“需要处理”通知之间的最短间隔。

**路径与辅助程序**

- `credentials_path`、`token_path`、`state_path`、`status_path`——默认是 `config.json` 旁边的同名文件。
- `reminders_exporter_path`、`reminders_apply_path`（空）——为空时依次使用：App 自带的辅助程序（`Contents/MacOS`）、源码目录中的 `build/helpers/`、用 `swift` 解释执行的 `macos/Helpers/` 中的 Swift 源文件。
- `reminders_source`（`eventkit`）——`eventkit` 通过 Apple 官方框架读取提醒事项。继承自上游的 `sqlite` 模式（直接读取提醒事项数据库）和 `auto`（EventKit 失败时退回 SQLite）都不受支持。

**继承自上游的 Google 日历模式**

`target_service` 为 `tasks`。上游项目还可以把提醒事项写成 Google 日历中的日程（`target_service: "calendar"`，配合 `calendar_id`、`default_duration_minutes`、`prefix_list`、`transparency` 和 `google_popup_minutes`）。引擎仍保留这一模式，但 App、共享客户端和本文档只支持 Google Tasks。

## 代理

| `proxy` | 行为 |
| --- | --- |
| `""`（默认） | 如果设置了 `HTTPS_PROXY` / `HTTP_PROXY` 环境变量就使用它们，否则使用 macOS 系统代理（“系统设置”→“网络”→ 你的网络连接 →“详细信息”→“代理”） |
| `"none"` | 始终直接连接，忽略系统代理和环境变量 |
| `"http://主机:端口"` | 所有 Google 请求都经过这个 HTTP 代理，例如 `http://127.0.0.1:7890` |

注意：

- 只接受 `http://` 和 `https://` 形式的代理地址。如果你的客户端只提供 SOCKS，请使用它的 HTTP 端口或“混合”（mixed）端口。
- 后台进程看到的代理不一定与浏览器相同。如果网页能正常打开、同步却报网络错误，请明确设置代理。
- **中国大陆：** 无法直接访问 Google。请运行代理客户端，并填入它的本地 HTTP 端口，例如：

  ```bash
  echo '{"proxy": "http://127.0.0.1:7890"}' | ltb config merge --json
  ```

  Clash 和 ClashX 默认使用 `7890` 端口，Clash Verge Rev 默认使用 `7897`；实际的“HTTP”或“混合”端口请以你客户端中的设置为准。如果客户端开启了 TUN / 增强模式，它会自行接管所有流量，此时保持 `""` 也可以。用于 Google 登录的浏览器同样需要能访问 Google。

## 同步间隔与 Google 配额

定时同步每隔 `sync_interval_seconds`（最小 60）开始一轮，从上一轮开始计到下一轮开始；如果某一轮耗时超过间隔，下一轮会立刻开始。本机提醒事项的改动会触发额外的同步，但最多每 `trigger_min_interval_seconds`（10 秒）一轮。

**使用共享客户端时**，由于所有用户共用同一份 Google 配额，引擎会强制采用更温和的节奏：无论设置如何，定时同步之间至少间隔 5 分钟，触发的同步之间至少间隔 30 秒。引擎每一轮都会重新判断，所以切换登录方式后立即生效。本机的改动仍会在几秒内到达 Google。

每一轮同步消耗的 Google Tasks API 请求数（N 为同步的列表数）：

- **没有任何改动时：** 大约 **1 + N** 次——读取一次你的任务列表，每个列表再读取一次。由于没有写入任何内容，核对用的重新读取会被跳过。
- **有写入时：** 大约 **1 + 2 × N** 次，外加每一处改动一次——每个列表多读取一次，用于核对标题和截止日期。
- 如果一个列表中的任务超过 100 个（包括已完成和最近删除的），每次读取每多 100 个任务就多一次请求。

仅空闲轮次的消耗：

| 同步间隔 | 1 个列表 | 3 个列表 |
| --- | --- | --- |
| 1 分钟（自有客户端默认） | 约 2,900 次/天 | 约 5,800 次/天 |
| 5 分钟（共享客户端） | 约 580 次/天 | 约 1,150 次/天 |

每一批本机改动都会多出一轮有写入的同步。自有客户端独享每天 50,000 次请求，所以 1 分钟的间隔绰绰有余。使用共享客户端时，所有用户的请求合计共用每天 50,000 次的配额。

## 命令行参考

`ltb` 是 App 内的一个小包装脚本（`Local Tasks Bridge.app/Contents/Resources/bin/ltb`），它会找到合适的 Python，并用你的配置文件运行引擎。在源码目录中也可以直接运行引擎：

```bash
python3 -B engine/local_tasks_bridge.py --config ~/.config/local-tasks-bridge/config.json status
```

有两个全局选项写在命令之前：`--language auto|en|zh` 设置本次运行的消息语言（例如 `ltb --language zh status`），`--version` 打印版本号。

需要读写提醒事项的命令（`lists`、`sync`、`approvals show`、`approvals apply`、`export`、`manage`）依赖于启动它们的那个 App 的提醒事项访问权限；在“终端”中运行时，就是“终端”本身。

### 机器可读的输出

加上 `--json` 后，命令会在所有工作完成后，向标准输出打印且仅打印一个 JSON 对象；进度信息输出到标准错误。成功时为 `{"ok": true, …}`，退出码为 0；失败时形如 `{"ok": false, "error": {"code": "…", "message": "…"}}`，退出码为下列之一：

| 退出码 | `error.code` | 含义 |
| --- | --- | --- |
| 1 | `failed` | 意外失败；详情见日志 |
| 2 | — | 命令行用法错误 |
| 3 | `auth_required` | 尚未登录 Google，或登录已过期、被撤销 |
| 4 | `account_binding_required` | 当前的 Apple 或 Google 账号与同步对应关系所属的账号不同 |
| 5 | `approval_required` | 计划超出了删除/完成的安全上限 |
| 6 | `reminders_unavailable` | 无法读写提醒事项（通常是权限问题） |
| 7 | `config_invalid` | 配置文件或合并的设置无效 |
| 8 | `oauth_client_missing` | 没有可用的 Google 客户端（既没有自有的，也没有共享的） |
| 9 | `network` | 无法连接 Google，请稍后重试 |
| 10 | `plan_changed` | 之前的确认与当前计划已不再一致 |

时间戳为 UTC 的 ISO 8601 格式。消息语言遵循 `language` / `LTB_LANG`。

### 查看信息

**`ltb version [--json]`**——引擎版本、Python 版本和引擎路径。

**`ltb status [--json]`**——当前状况、简要说明、建议的操作、上次成功时间、连续失败次数、待确认的暂缓更改、登录与客户端状态、选中的列表、同步间隔和登录项状态。只读取本地文件：不联网、不访问提醒事项，瞬间完成。`condition` 为以下之一：`setup_required`、`auth_required`、`account_binding_required`、`mutation_approval_pending`、`mutation_blocked`、`paused`、`running`、`failed`、`never_synced`、`status_unreadable`、`agent_stopped`、`attention`、`healthy`、`unknown`（见[故障排除](troubleshooting.zh-CN.md#状态说明)）。`loop_running` 表示后台同步循环是否在运行。

**`ltb lists [--google] [--json]`**——列出所有提醒事项列表及其所属账号（不受 `include_lists` 限制）。加上 `--google` 还会列出你的 Google 任务列表（需要联网并已登录）。

**`ltb doctor [--online] [--json]`**——检查配置、辅助程序、登录文件、登录项和上一轮结果，并给出一条下一步建议。默认只在本地只读运行，不显示保存的错误原文和路径，所以输出可以放心分享。`--online` 还会刷新 Google 登录并调用 Tasks API。

### 设置

**`ltb config show [--json]`**、**`ltb config merge --json`**、**`ltb config init [--force] [--json]`**——见[修改设置](#修改设置)。**`ltb config validate [--json]`** 检查 `config.json` 但不做任何修改。

### Google 登录

**`ltb client import <路径> [--json]`**——校验一个类型为**桌面应用**的 Google OAuth 客户端 JSON，把它复制为 `credentials.json` 并选用它（`oauth_client: "custom"`）。Web 客户端会被拒绝并附上说明。输出客户端 ID 的提示片段。

```bash
ltb client import ~/Downloads/client_secret_*.apps.googleusercontent.com.json
```

**`ltb client status [--json]`**——当前生效的客户端（`custom`、`bundled` 或 `missing`）、是否有自有客户端、本版本是否带有共享客户端。

**`ltb auth [--no-browser] [--json]`**——登录 Google（PKCE，回环地址 `127.0.0.1` 回调）。会打开默认浏览器；加上 `--no-browser` 则打印需要打开的网址。最多等待 5 分钟。

**`ltb account [--json]`**——刷新登录并验证 Tasks API 可用；输出账号邮箱和任务列表数量。

**`ltb signout [--revoke] [--json]`**——删除 `token.json`（会先做私密备份）；加上 `--revoke` 会先请 Google 撤销该令牌。同步对应关系会保留：重新登录同一个 Google 账号即可从上次的位置继续。

### 同步

**`ltb sync [--dry-run] [--no-delete-stale] [--json]`**——在前台运行一轮同步。`--dry-run` 只计算并打印计划，不做任何更改。`--no-delete-stale` 在两个方向上都不同步完成和删除——设置向导的首次同步就用了它。如果计划超出安全上限，不会写入任何内容，命令以退出码 5 结束。

```bash
ltb sync --dry-run                    # 会发生什么？
ltb sync --dry-run --no-delete-stale  # 同上，但不含完成和删除
ltb sync                              # 正式执行
```

JSON 结果中包含 `summary` 计数（`apple_exported`、`google_lists`、`inserted`、`updated`、`unchanged`、`completed`、`deleted`、`duplicate_deleted`、`google_applied`、`bidir_conflicts`、`skipped_invalid`），以及以 `<目标>.<操作>` 为键的 `plan` 计数，例如 `google_tasks.create`、`google_tasks.complete`、`google_tasks.delete`、`google_tasks.create_list`、`apple_reminders.create`、`apple_reminders.complete`、`apple_reminders.delete`。

**`ltb pause [--json]`**、**`ltb resume [--json]`**——创建或删除 `paused` 文件。暂停期间，定时和触发的同步都会跳过。

**`ltb sync-now [--json]`**——触碰 `sync-now` 文件；后台循环会在大约一秒内开始一轮同步。

**`ltb run-loop [--log-file 路径] [--log-max-bytes N]`**——后台调度器本身。App 会替你运行它；只在测试时手动运行。每个配置文件夹同时只能运行一个循环：当另一个循环持有 `run-loop.lock` 时，第二个会以状态码 1 退出。要停止循环，请向它发送 SIGTERM（或按 Control-C），并留出最多 30 秒——空闲的循环会立即退出，正在同步的循环会先完成这一轮，保证状态不会只写了一半。加上 `--log-file` 时，可读的输出会写入这个私密日志，并按大小轮转。

### 被暂缓的更改

**`ltb approvals show [--json]`**——在不写入任何内容的前提下计算下一轮计划（需要联网并访问提醒事项），列出等待确认的删除和完成：操作类型、列表和标题。标题只会出现在这里、审核窗口和确认对话框中，绝不会写入 `status.json` 或日志。

**`ltb approvals apply <指纹> [--json]`**——在一次正式同步中执行且只执行这一组删除和完成。如果计划在此期间发生了变化，不会执行任何操作，命令以 `plan_changed` 失败；请重新用 `approvals show` 查看。

**`ltb approvals hold <指纹> [--json]`**——记录你选择暂缓；后台同步会继续同步其他所有内容，稍后再询问。

```bash
ltb approvals show
ltb approvals apply 3b6f…e91c   # 上面显示的 64 位“删除/完成”指纹
```

### 恢复

**`ltb manage [操作] [--yes]`**——“终端”中的交互式菜单。也可以直接指定操作：

| 操作 | 作用 |
| --- | --- |
| `status` | 查看状态（只读） |
| `check` | 在线检查 Google 连接（可能会刷新登录） |
| `reconnect` | 安全地重新连接 Google：备份私密文件、暂停后台同步、确认账号，并且只在你确认后重建同步对应关系，期间不同步删除和完成 |
| `restart` | 重启后台同步 |
| `approve` | 在“终端”中审核被暂缓的删除和完成，然后执行或暂缓 |

`--yes` 会对所有确认都回答“是”，仅用于受控的测试。

**`ltb rebuild [--dry-run] [--yes] [--json]`**——在你确认当前使用的 Apple 和 Google 账号正是要同步的这一对之后，用于从 `account_binding_required` 中恢复。`--dry-run` 显示重建将会做什么——以空的同步对应关系、关闭完成与删除同步的方式计算——但不写入任何内容。`--yes` 会暂停后台循环、备份私密文件、把旧的 `state.json` 移入备份，然后执行一次安全同步来建立新的对应关系，整个过程都持有同步锁。两边都不会删除任何内容。App 中的“重新连接 Google…”和 `ltb manage reconnect` 以交互方式达到同样的结果。

**`ltb migrate [--from 路径] [--dry-run] [--force] [--yes] [--json]`**——导入早期安装，见 [migration.zh-CN.md](migration.zh-CN.md)。

### 登录项与卸载

**`ltb agent install --app <.app 路径> [--json]`**——写入并加载在登录时启动 App 的登录项（LaunchAgent `io.github.siyuanj.local-tasks-bridge`）；只在它尚未加载时才加载（加上 `--no-load` 则只写入不加载）。**`ltb agent uninstall [--bootout] [--json]`** 删除登录项，此后 App 不再在登录时启动。在“终端”中运行时，它还会停止正在运行的任务；App 自己的调用（以 `LTB_CALLER=app` 标记）只有加上 `--bootout` 才会停止。**`ltb agent status [--json]`** 报告 `installed`、`loaded`、`label`、`plist` 和 `program`。App 会自动管理这些。

**`ltb uninstall [--revoke] [--delete-data] --yes [--json]`**——移除登录项；在“终端”中运行时还会停止正在运行的任务（登录时启动的 App 会因此退出）；`--revoke` 同时撤销 Google 授权；`--delete-data` 同时删除 `~/.config/local-tasks-bridge/` 和日志。它不会删除 App：请自己把它移到废纸篓，或者使用 App 中的“卸载…”（运行这条命令后把 App 移到废纸篓），或安装脚本的 `--uninstall`（先退出 App，再运行这条命令，然后删除 App 和 `ltb` 链接）。

### 其他终端命令

- `ltb export`——以 JSON 打印选中的提醒事项（包含你的数据，请勿分享）。
- `ltb init-config`——写入一份原始的引擎模板（建议改用 `ltb config init`）。
- `ltb gcloud-login`——通过 gcloud 命令行工具登录（高级用法，遗留功能）。
- 不带 `--json` 的 `ltb doctor` 会打印一份易读的报告。

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `LTB_LANG` | `en` 或 `zh`：`language` 为 `auto` 时引擎消息使用的语言。App 会按自身的界面语言设置它。未设置时会依次参考 `LC_ALL`、`LC_MESSAGES`、`LANG` 和 macOS 的语言设置。 |
| `LTB_PYTHON` | 指定使用的 Python 解释器（3.9 或更高）；未指定时依次使用 App 内置的 Python、`/usr/bin/python3`（仅在已安装命令行工具时）、Homebrew 的 `python3` |
| `HTTPS_PROXY`、`HTTP_PROXY`、`NO_PROXY` | 在 `proxy` 为 `""` 时生效 |
| `XDG_CONFIG_HOME` | 把配置文件夹移到 `$XDG_CONFIG_HOME/local-tasks-bridge`。登录时启动的 App 读不到你在 shell 配置文件中设置的变量，所以如果只在“终端”中设置它，`ltb` 和 App 会使用不同的文件夹。 |
| `LTB_EVENT_STREAM`、`LTB_APP_BUNDLE`、`LTB_CALLER` | 由 App 为它启动的引擎设置（`LTB_CALLER=app` 标记 App 自己的调用）；请勿手动使用 |

以下变量仅用于测试，App 从不设置：`LTB_TASKS_API`、`LTB_OAUTH_AUTH_URL`、`LTB_OAUTH_TOKEN_URL`、`LTB_OAUTH_USERINFO_URL`、`LTB_OAUTH_REVOKE_URL`（必须是 `https://…` 或回环地址的 `http://` 网址）、`LTB_REMINDERS_EXPORTER`、`LTB_REMINDERS_APPLY`（辅助程序路径）、`LTB_BUNDLED_OAUTH_CLIENT`（路径）、`LTB_LAUNCH_AGENTS_DIR`、`LTB_NO_LAUNCHCTL=1` 和 `LTB_LOG_DIR`。见 [CONTRIBUTING.zh-CN.md](../CONTRIBUTING.zh-CN.md)。
