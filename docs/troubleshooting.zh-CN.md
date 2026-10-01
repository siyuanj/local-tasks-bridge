# 故障排除与常见问题

[English](troubleshooting.md) · **简体中文**

从这里开始：

1. **点按菜单栏图标。** 最上面几行会告诉你当前发生了什么、下一步该做什么。
2. **在“终端”中运行 `ltb status`。** 它瞬间完成，只读取本地文件。`ltb doctor` 会检查安装情况；`ltb doctor --online` 还会测试 Google 连接。
3. **查看日志：** 在菜单中选择“打开日志”。日志里有任务标题，所以请自己阅读，不要直接发给别人（见[日志与诊断信息](#日志与诊断信息)）。

## 状态说明

`ltb status` 和 App 会报告以下状况之一：

| 状况 | 含义 | 怎么办 |
| --- | --- | --- |
| `healthy` | 提醒事项与 Google Tasks 已同步 | 无需操作 |
| `running` | 正在同步 | 稍等片刻 |
| `paused` | 你暂停了同步 | 选择“恢复同步”，或运行 `ltb resume` |
| `setup_required` | 尚未完成设置，或缺少提醒事项辅助程序 | 选择“完成设置…”；如果缺少辅助程序，请重新安装 App |
| `never_synced` | 还没有同步过 | 在设置向导中完成首次同步 |
| `attention` | 试运行或登录已成功，但之后还没有完成一次完整同步 | 完成首次同步，或等下一轮同步后再看 |
| `auth_required` | 尚未登录 Google，或登录已过期、被撤销 | 选择“重新连接 Google…”，或运行 `ltb auth`，见[下文](#登录已过期或被撤销) |
| `account_binding_required` | 当前的 Apple 或 Google 账号与同步对应关系所属的账号不同 | 见[账号绑定已变化](#账号绑定已变化) |
| `mutation_approval_pending` | 一批较多的删除或完成被暂缓，其他改动照常同步 | 在“查看待确认的更改…”中作答，见[下文](#批量更改等待确认) |
| `mutation_blocked` | 某次同步因计划超出安全上限而停止 | 选择“查看待确认的更改…”，或运行 `ltb approvals show` |
| `failed` | 上一轮同步失败 | 运行 `ltb doctor --online`，再查看日志；下面各节涵盖了常见原因 |
| `agent_stopped` | 后台同步没有运行 | 打开 Local Tasks Bridge；完成设置后它会在登录时自动启动 |
| `status_unreadable` | 无法读取状态文件 | 备份 `~/.config/local-tasks-bridge/status.json`；下一轮同步后会重新生成 |
| `unknown` | 无法确定当前状态 | 运行 `ltb manage check`，再查看日志 |

同时符合多种状况时，会显示最紧急的那一种——例如同步失败会先于“后台同步没有运行”显示。

## 安装与打开 App

### macOS 提示无法打开 App，或“未打开”

1.0 版采用临时签名，未经 Apple 公证，所以用浏览器下载的副本第一次启动时会被 Gatekeeper 拦下：

- **macOS 15 Sequoia 及更高版本：** 点按“完成”，打开“系统设置”→“隐私与安全性”，滚动到“安全性”部分，在关于 Local Tasks Bridge 的提示旁点按“仍要打开”，再用密码或触控 ID 确认。
- **macOS 13 和 14：** 按住 Control 键点按 App，选择“打开”，再点按“打开”。

也可以让安装脚本来安装这个 zip：它会校验文件并清除隔离标记，因此不会出现提示：

```bash
curl -fsSL https://raw.githubusercontent.com/siyuanj/local-tasks-bridge/main/install.sh \
  | bash -s -- --zip ~/Downloads/LocalTasksBridge-macos-arm64.zip
```

如果你更喜欢手动处理，并且已经用 `SHA256SUMS` 核对过下载的文件：`xattr -dr com.apple.quarantine ~/Applications/"Local Tasks Bridge.app"`。

### macOS 提示 App 已损坏

这通常说明下载不完整，或者 zip 被某个解压工具解压时破坏了 App 的签名。请重新下载 zip，用 `SHA256SUMS` 核对，然后用“访达”解压，或用安装脚本的 `--zip` 选项安装。校验值不一致的副本请不要运行。

### 打开之前，先把 App 移到“应用程序”文件夹

如果直接从“下载”文件夹或磁盘映像中打开 App，macOS 可能会在一个隐藏的临时位置运行它，重启后登录项就找不到它了。请先把 **Local Tasks Bridge.app** 移到 `~/Applications` 或 `/Applications`，再打开。

### 提示“需要 Python 3.9 或更高版本”

同步引擎运行在 Python 上。发布版自带 Python，所以这条提示通常只会出现在从源码构建的 App 上：它会依次查找 Apple 命令行工具中的 Python 和 Homebrew 的 Python。安装命令行工具：

```bash
xcode-select --install
```

然后退出并重新打开 App。其他办法：从 <https://www.python.org/downloads/> 安装 Python，或运行 `brew install python`。如果想让 `ltb` 使用某个特定的解释器，请设置 `LTB_PYTHON=/path/to/python3`。

### `ltb: command not found`

安装脚本会把 `ltb` 链接到 `~/.local/bin`。请把这个文件夹加入 `PATH`：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

然后打开一个新的终端窗口。你也可以随时用完整路径运行它：`~/Applications/"Local Tasks Bridge.app"/Contents/Resources/bin/ltb status`。

### 从源码构建失败

- 出现 `xcode-select: error` 或找不到 `swiftc`：用 `xcode-select --install` 安装命令行工具。
- macOS 更新后出错：命令行工具可能需要更新。请查看“系统设置”→“通用”→“软件更新”，或者删除 `/Library/Developer/CommandLineTools` 后重新安装。
- 提示 Python 版本低于 3.9：命令行工具自带合适的 `python3`；请确认 `xcode-select -p` 能输出一个路径。

## 提醒事项访问权限

### 提醒事项访问权限被拒绝或缺失

表现：菜单中提示 *Local Tasks Bridge 无法读取提醒事项*，或命令以 `reminders_unavailable`（退出码 6）失败。

1. 打开“系统设置”→“隐私与安全性”→“提醒事项”，打开 **Local Tasks Bridge** 的开关。在 macOS 14 及更高版本上，App 需要完全访问权限，因为它不仅读取，还会写入提醒事项。
2. 如果列表中没有它，或者打开开关也没用，请重置这项权限，让 macOS 重新询问，然后退出并重新打开 App，点按“允许”：

   ```bash
   tccutil reset Reminders io.github.siyuanj.LocalTasksBridge
   ```

如果 App 提示它只能添加提醒事项，说明它只获得了“仅添加”权限：请在同一位置改为完全访问。如果访问受到“屏幕使用时间”或设备管理描述文件的限制，请联系这台 Mac 的管理者。

### 更新后 macOS 再次请求提醒事项访问权限

1.0 版采用临时签名。macOS 按代码签名记住隐私权限，而临时签名每次构建都会变，所以更新后 macOS 可能把 App 当成新的 App 再次询问。点按“允许”即可。如果旧的条目一直处于关闭状态，请使用上面的 `tccutil` 命令。以后的版本计划使用 Developer ID 签名，届时权限在更新后会自动保留。

### 在“终端”中运行 `ltb` 时请求提醒事项访问权限

macOS 把提醒事项访问权限授予启动进程的那个 App。由菜单栏 App 运行引擎时，辅助程序使用的是这个 App 的权限。当你在“终端”中运行 `ltb sync`、`ltb lists` 或 `ltb approvals show` 时，负责的 App 是“终端”（或 iTerm、你的编辑器），所以 macOS 会为它请求权限。你可以允许，也可以把同步交给菜单栏 App 去做。`ltb status` 和 `ltb doctor` 不读取提醒事项。

## Google 登录

### 登录已过期或被撤销

App 提示 *请重新登录 Google 以继续同步*，或 `ltb status` 显示 `auth_required`。常见原因：你在 <https://myaccount.google.com/permissions> 中移除了应用的访问权限；你自己的客户端仍处于 **Testing（测试）** 状态，Google 会在 7 天后让登录失效（见[发布应用](google-cloud-setup.zh-CN.md#4-发布应用audience)）；登录大约六个月没有被使用；或者 Google 的安全事件。

解决办法：选择“重新连接 Google…”（“设置”→“Google”），或运行 `ltb auth`。同步会在下一轮自动恢复。只要登录的是同一个 Google 账号，同步对应关系就会保留。

### Google 未验证此应用

所有没有经过 Google 验证的 OAuth 客户端都会显示这个警告——包括维护者完成验证之前的共享客户端，以及你自己创建的个人客户端。点按“高级”，再点按“转至……（不安全）”即可。授权页面会准确列出你授予的权限：你的任务，以及你的基本 Google 身份信息（账号 ID 和邮箱地址）。桥接在你的 Mac 上运行，你的任务绝不会发送给维护者。详见 [PRIVACY.zh-CN.md](../PRIVACY.zh-CN.md)。

### 因为取消勾选了任务权限而登录被拒

Google 的授权页面允许你取消勾选单项权限。没有**“创建、修改、整理和删除你的所有任务”**这一项，桥接就无法工作，所以它会立即拒绝这次登录。请重新登录，并保持勾选。

### 浏览器没有打开，或登录超时

- 登录最多等待五分钟。超时了就重新开始。
- 想自己打开登录网址：运行 `ltb auth --no-browser`，它会打印出来。
- 你批准之后，Google 会把浏览器跳转到你本机的 `http://127.0.0.1:<端口>/`。如果某个浏览器代理扩展把本地地址也转发给代理，这个页面就会打不开；请把 `127.0.0.1` 和 `localhost` 加入它的直连（不代理）列表。

### Google 页面上显示的错误

`access_denied`、`redirect_uri_mismatch`、`invalid_client`、“This app is blocked”、`admin_policy_enforced` 和 `org_internal` 的说明，见 [Google Cloud 设置指南中的常见错误](google-cloud-setup.zh-CN.md#常见错误)。

### 没有共享客户端可选，或它不再接受新用户

共享客户端只存在于包含它的发布版中，源码构建中永远没有。在维护者完成 Google 验证之前，Google 允许它累计最多 100 位用户。如果它不可用或已满，请使用[你自己的客户端](google-cloud-setup.zh-CN.md)——大约十分钟就能完成，而且没有这个限制。

## 账号绑定已变化

**它在保护什么。** 同步对应关系记录了哪条提醒事项对应哪个 Google 任务。它与你所选列表所在的 Apple 账号以及你的 Google 账号 ID 绑定；保存的只是这些标识符的哈希值。如果桥接突然看到一个不同的 Google 账号，或来自另一个 Apple 账号的提醒事项，继续使用这份对应关系可能会让它把所有条目都当作已删除，或者写进错误的账号。所以它会在读写任何列表之前停下来。

**常见原因：** 不小心登录了另一个 Google 账号；这台 Mac 的 iCloud 账号换了；配置文件夹是从另一台 Mac 或另一个用户那里复制来的；很早期的、没有绑定信息的同步对应关系。

**怎么办：**

- **不小心登录了错误的 Google 账号：** 选择“重新连接 Google…”，登录正确的账号。同步会继续，不需要重建任何东西。
- **账号确实要换：** 在“设置”→“Google”中选择“重新连接 Google…”，或在“终端”中运行 `ltb manage reconnect`。它会检查 Google 连接、备份你的私密文件、显示它找到的 Apple 和 Google 账号，并且只在你确认后，把旧的同步对应关系移到 `~/.config/local-tasks-bridge/backups/`，然后先试运行、再执行一次不同步删除和完成的同步来建立新的对应关系。两边都不会删除任何东西。以前同步过的条目会通过备注末尾的同步标记，或通过标题和日期重新匹配；如果换成了新的 Google 账号，你的提醒事项会被复制到新账号中，而新账号中已有的任务会被导入“提醒事项”。
- **在“终端”中、不使用菜单时：** `ltb rebuild --dry-run` 会显示重建将做什么，`ltb rebuild --yes` 则执行重建，保护措施相同——先备份，替换对应关系期间暂停后台循环并持有同步锁，并且不删除任何内容。
- 重新登录**同一个** Google 账号时永远不需要这样做：1.0 把对应关系绑定到账号 ID，而不是某一次特定的登录。早期版本建立的对应关系会在第一次同步时自动升级。

## 批量更改等待确认

如果一份计划要删除或完成**超过 25 个**条目，或超过桥接所管理条目的 **25%**，就需要你确认。后台同步只会暂缓这些删除和完成；新建和修改照常同步。当同一组更改连续两轮出现后，App 会打开**“查看待确认的更改”**窗口，按类型和列表列出被暂缓的更改。

- **“执行 N 项更改”**会且只会执行这一组更改。如果在此期间这组更改发生了变化，就不会执行任何操作，窗口会显示新的计划。
- **“暂缓”**让这组更改继续等待。6 小时内不会再问你，其他改动照常同步。
- 如果你没有回答就关闭了窗口，12 小时后会再次询问；随时可以通过菜单中的“查看待确认的更改…”重新打开它。
- 如果这些计划中的删除消失了——例如你恢复了这些条目——这个问题也会随之撤销。

如果引擎在没有 App 的情况下运行（例如在“终端”中运行 `ltb run-loop`），则会改用 macOS 对话框询问，按钮为“执行”和“暂缓”（默认）。

你随时可以审核这组更改：在菜单中选择“查看待确认的更改…”，或在“终端”中：

```bash
ltb approvals show                  # 查看被暂缓的内容（含标题）
ltb approvals apply <指纹>          # 执行且只执行这一组
ltb approvals hold <指纹>           # 继续暂缓
```

常见原因，以及是否应该执行：

- 你有意完成或删除了很多条目 → **执行**。
- 某个列表中的条目在“提醒事项”或 Google 中被全部删除了 → 只有确实是你的本意时才执行。
- 重启或账号出问题之后，“提醒事项”或 iCloud 返回了不完整的数据 → **暂缓**并等待；这份计划通常会自己消失。

安全上限可以通过 `max_destructive_changes` 和 `max_destructive_ratio` 修改（见[配置说明](configuration.zh-CN.md#设置项参考)）。

## 重命名、移动和取消选择列表

列表按名称精确配对。改变同步哪些列表，永远不会被当作删除：桥接只会完成或删除那些仍被选中、并且仍与同一个 Google 列表配对的列表中的条目，其他列表的条目一律不动。

- **取消选择某个列表**只会停止同步它。它的提醒事项和 Google 任务都保持原样；以后再选上它时，会从上次的位置继续同步。
- **重命名已同步的列表：** 请在**两边**都改成同一个新名称，然后在“设置…”→“列表”中更新所选列表；桥接会保留所有关联。只在一边改名的列表会被当作新列表：桥接会在另一边创建一个使用新名称的列表并把条目复制进去，而另一边原来的列表保持不动。删除你不需要的那份副本即可，删除会同步过去。
- **删除已同步的列表：** 在“提醒事项”中删除，不会影响 Google 列表及其中的任务。如果在 Google 中删除了一个在 Mac 上仍被选中的列表，桥接会根据“提醒事项”重新创建它；如果你想让它彻底消失，请先取消选择。
- **把条目移到另一个列表：** 请在“提醒事项”中操作。桥接会在旧列表中删除 Google 副本、在新列表中重新创建（这次删除计入安全上限）。在 Google Tasks 中移动条目，桥接无法理解：它看到的是一个条目从一个列表中消失，又带着别的条目的同步标记出现在另一个列表里，结果可能被移回去，也可能被删除。

## 冲突

冲突是指同一条目在两轮同步之间、在两边都被修改了。

- 使用 `newer_wins`（默认）时，最近修改的版本整体胜出——标题、备注、日期和完成状态。你不需要做什么。
- 使用 `skip` 时，这一条在两边都保持不动，本轮同步被报告为**失败**（“Bidirectional conflicts left Apple Reminders and Google Tasks unsynced”），而其他条目照常同步，同步对应关系也会被保存。请在一边修改这一条使两边一致，或把该列表改为 `newer_wins`。
- 如果某个 Google 任务被删除之后，你又在 Mac 上编辑了对应的提醒事项，而且这次编辑比删除更晚，桥接会在 Google 中重新创建这个任务，而不是删除提醒事项。

## 网络与代理

表现：提示 *现在无法连接 Google*，退出码 9（`network`），或日志中出现超时和 TLS 错误。

- 确认 Mac 已联网，并且浏览器能打开 <https://tasks.google.com>。
- **中国大陆：** 无法直接访问 Google。请运行代理客户端（Clash、ClashX、Clash Verge 等），并在“设置”中填入它的本地 HTTP 或“混合”（mixed）端口，例如 `http://127.0.0.1:7890`（Clash 和 ClashX）或 `http://127.0.0.1:7897`（Clash Verge Rev）：

  ```bash
  echo '{"proxy": "http://127.0.0.1:7890"}' | ltb config merge --json
  ```

  然后用 `ltb account` 检查。如果客户端运行在 TUN / 增强模式下，就不需要任何设置。
- **浏览器能用，同步却失败：** 后台进程不一定使用与浏览器相同的代理。请按上面的方法明确设置代理。
- **设置了代理，但当前网络中没有这个代理：** 把代理设为 `none`，或改回系统默认的 `""`。
- 只支持 HTTP(S) 形式的代理地址；如果客户端只提供 SOCKS，请使用它的 HTTP 或混合端口。

临时性的读取失败——连接中断、超时、HTTP 429 和 5xx——最多重试 3 次。失败的写入不会被盲目重复——唯一的例外是把任务标为完成，而且只有在 Google 确认该任务仍未完成时才会重试——所以网络抖动不会造成重复。下一轮同步会把进度补上。

## 重复的条目

- **同一条提醒事项对应了多个 Google 任务**（同步标记相同）时，多余的会被自动清理；这种清理计入安全上限。
- **两个条目标题相同没关系。** 条目是按身份标识匹配的，而不是按标题；按标题匹配只是在标题唯一时使用的后备手段。
- **一个 Google 任务和一条提醒事项说的是同一件事，却变成了两个条目：** 导入已有的 Google 任务时，只有当标题和截止日期完全相同，才会与一条未完成的提醒事项关联；否则会新建第二条提醒事项。删除其中一个即可，删除会同步过去。
- **只在一边改名的列表**会让另一边的新列表中多出一份条目副本（[原因](#重命名移动和取消选择列表)）。删除不需要的那份即可。
- **一下子出现很多重复：** 通常是有两个同步工具在处理同一批列表——另一个同步 App、仍在运行的旧安装（见 [migration.zh-CN.md](migration.zh-CN.md)），或者第二台 Mac 上的 Local Tasks Bridge（[为什么不行](#能在两台-mac-上同时运行吗)）。请先停掉另一个，再删除多余的副本。

## 备注末尾的同步标记

每个已同步的 Google 任务，备注末尾都有几行文字：

```text
Synced from Apple Reminders.
List: My Tasks
Source UID: 9f2c41…
Source Digest: 7a1e05…
```

**Source UID** 标识对应的提醒事项，**Source Digest** 是已同步内容的指纹，**List** 一行仅供参考。同步标记始终是英文，并且永远不会被复制到“提醒事项”中——你写在它上面的备注会正常同步。

请不要删除或修改这几行。如果同步标记丢了，桥接通常能根据同步对应关系把它补回来；但如果你同时还改了标题，它就无法确认这是同一个任务，可能会产生重复。卸载后同步标记仍会留在 Google 中，届时你可以把它删掉。

## 具体时间

Google Tasks 只保存截止**日期**。一条周二 15:00 到期的提醒事项，在 Google 中显示为周二到期；具体时间保留在“提醒事项”中。在 Google 中编辑这个任务不会丢掉这个时间：日期没变时，时间保持不变；如果你在 Google 中改了日期，提醒事项会移到新日期的同一时间。在 Google 中清除截止日期，Mac 上也会随之清除。你在“提醒事项”中设置的提醒时间不会被桥接改动。

## 重复的提醒事项

Google Tasks 的 API 中没有重复规则。一条重复的提醒事项在 Google 中只显示为当前这一次的单个任务；重复规则保留在“提醒事项”中，以它为准。当这条提醒事项在“提醒事项”中进入下一次时，Google 任务的截止日期也会跟着更新。在 Google 中创建的重复任务，到 Mac 上会变成一次性的提醒事项。重复的提醒事项还没有经过真实账号的验收测试：请在“提醒事项”中而不是在 Google 中完成它们，并留意最初几次的表现。

## 子任务

子任务不会对应。父子结构在两个方向上都不会被复制；子任务在另一边可能显示为一个普通的顶层条目。在已同步的列表中请不要依赖子任务。

## 截止日期很远的提醒事项

没有时间窗口的限制：有截止日期的提醒事项，无论多久以后到期都会同步。（引擎的 `lookahead_days` 设置只用于继承自上游的 Google 日历模式。）

## 改动多久会同步过去？

| 改动来源 | 何时到达另一边 |
| --- | --- |
| 在这台 Mac 的“提醒事项”中 | 通常几秒内——“提醒事项”一报告有改动，App 就会开始一轮同步（额外的同步最多每 10 秒一轮，使用共享客户端时最多每 30 秒一轮） |
| 在 iPhone、iPad 或 Watch 上 | iCloud 把改动送到这台 Mac 之后，再过几秒 |
| 在 Google 中（Tasks、Gmail、日历、Gemini） | 下一轮定时同步时：约 1 分钟内（自有客户端）或约 5 分钟内（共享客户端） |
| Mac 睡眠或未登录期间 | Mac 唤醒并且你登录之后 |

一轮同步本身需要几秒——通过较慢的代理或条目很多时会更久。“立即同步”会马上开始一轮。

## 日志与诊断信息

| 文件 | 内容 |
| --- | --- |
| `~/Library/Logs/LocalTasksBridge/engine.log` | 每一轮做了什么，**包含任务标题** |
| `~/Library/Logs/LocalTasksBridge/app.log` | App 与 launchd 的输出 |
| `~/.config/local-tasks-bridge/status.json` | 上一轮的结果：状态、时间、数量和哈希值，绝不包含标题 |

可以通过菜单中的“打开日志”或“打开数据文件夹”查看，也可以用“控制台”App。引擎日志超过大约 5 MB 时会轮转。

需要求助时，请分享不含你个人数据的内容：

- 菜单中的“拷贝诊断信息”会拷贝一份不含标题和令牌的报告。
- `ltb doctor`（或 `ltb doctor --json`）显示各项检查和上一轮结果，不包含保存的错误原文和路径。

发布之前请先自己读一遍。切勿公开日志、`token.json`、`credentials.json`、`state.json`，以及 `ltb export` 或 `ltb approvals show` 的输出。报告问题请使用问题模板；安全问题请按 [SECURITY.md](../SECURITY.md#安全政策简体中文) 私下报告。

## 完全重置

这会移除 Local Tasks Bridge 以及它在这台 Mac 上保存的所有内容。你的提醒事项和 Google 任务都会保留。

1. 退出 App（菜单 →“退出 Local Tasks Bridge”）。
2. 移除登录项、撤销登录并删除数据：

   ```bash
   ltb uninstall --revoke --delete-data --yes
   ```

   或者手动执行：

   ```bash
   launchctl bootout gui/$(id -u)/io.github.siyuanj.local-tasks-bridge
   rm -f ~/Library/LaunchAgents/io.github.siyuanj.local-tasks-bridge.plist
   rm -rf ~/.config/local-tasks-bridge ~/Library/Logs/LocalTasksBridge
   ```

   删除 `~/.config/local-tasks-bridge` 也会删除你导入的 Google 客户端（`credentials.json`）；如果以后还想用，请先留一份副本。
3. 重置提醒事项访问权限：`tccutil reset Reminders io.github.siyuanj.LocalTasksBridge`
4. 把 App 移到废纸篓，并删除 `~/.local/bin/ltb`。
5. 如果没有使用 `--revoke`，请在 <https://myaccount.google.com/permissions> 中移除访问权限。

如果以后在同一台 Mac 上重新安装，首次同步通常能通过备注末尾的同步标记找回以前同步过的条目，因此不会产生重复。

## 常见问题

### 维护者能看到我的任务吗？

不能。桥接只与你 Mac 上的“提醒事项”和 Google 通信。维护者没有运行任何服务器，也没有统计分析和遥测。使用共享客户端时，Google 知道你授权了维护者的“Local Tasks Bridge”客户端，维护者能在 Google Cloud 中看到一些汇总数字，例如用户数和 API 请求数——但看不到你是谁，也看不到你的任务。详见 [PRIVACY.zh-CN.md](../PRIVACY.zh-CN.md)。

### 能在两台 Mac 上同时运行吗？

对于同一组账号，请只在**一台** Mac 上运行。每个安装都有自己的同步对应关系，而它用来识别提醒事项的标识符与具体的 Mac 有关，所以第二台 Mac 同步同样的列表会产生重复。你的其他 Apple 设备仍然可以通过 iCloud 看到所有改动。

### Mac 睡眠时还会同步吗？

不会。它运行在你已登录的用户会话中。在此期间别处的改动，会在 Mac 唤醒后同步。一台一直开着的 Mac——哪怕是旧机器——很适合用来做这个桥接。

### 能只单向同步吗？

可以，按列表设置：在 [`list_policies`](configuration.zh-CN.md#按列表的同步策略) 中把 `direction` 设为 `apple_to_google` 或 `google_to_apple`。也可以用 `delete_propagation: false` 让某个列表不同步完成和删除。

### 能同时使用多个 Google 账号吗？

每个 Mac 用户账号对应一个 Google 账号，同步对应关系与它绑定。

### 为什么 Google 中已完成的任务没有出现在“提醒事项”里？

导入已有的 Google 任务时，会跳过已完成的任务，免得多年的历史记录塞满“提醒事项”。同步之后才完成的任务会保持关联，两边都显示为已完成。

### 卸载会删除我的任务吗？

不会。卸载只会移除 App、它的登录项，以及（如果你要求）它的本地数据。提醒事项和 Google 任务都保持原样，包括 Google 任务备注末尾的同步标记。

### 收费吗？

不收费。Local Tasks Bridge 以 MIT 许可证开源。Google 不对 Tasks API 收费，创建你自己的 Google Cloud 项目也不需要结算账号。
