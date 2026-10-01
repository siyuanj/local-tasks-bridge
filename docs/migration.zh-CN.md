# 从早期安装迁移

[English](migration.md) · **简体中文**

Local Tasks Bridge 1.0 可以接管以下两种早期安装，而不会丢失 Google 登录和同步对应关系——因此不会有任何条目被重新创建、重复或删除：

| | 2026 年 9 月的私有试用版 | 上游项目 |
| --- | --- | --- |
| 名称 | Local Tasks Bridge 试用版 | `syncweave-labs/reminders-task-bridge`（“iCloud Reminders ↔ Google Tasks Sync”） |
| 设置文件 | `~/.config/reminders-task-bridge-trial/daily-config.json` | `~/.config/icloud-reminders-google-sync/config.json` |
| 登录项 | LaunchAgent `com.icloud-reminders-google-sync` | LaunchAgent `com.icloud-reminders-google-sync` |
| 程序文件 | `~/.local/share/icloud-reminders-google-sync/`，以及权限宿主 App `~/Applications/Local Tasks Bridge.app`（标识符 `local.reminders.tasks.bridge`） | `~/.local/share/icloud-reminders-google-sync/`，以及 `~/Applications` 中名为 `Google Tasks ….command` 的访达管理脚本 |
| 日志 | `~/Library/Logs/icloud-reminders-google-sync/` | `~/Library/Logs/icloud-reminders-google-sync/` |

如果两者都存在，会导入试用版。可以用 `--from` 明确指定。

## 导入会做什么

1. 找到早期的设置文件（或 `--from` 指定的那个）。如果这台 Mac 上已经有 1.0 的配置，它会停止——加上 `--force` 则仍会导入，并备份被替换的文件。
2. 以 1.0 的默认设置为基础，加上你以前的选择，写入新的 `~/.config/local-tasks-bridge/config.json`：选中的列表、按列表的策略、同步方向、删除与冲突设置、无日期条目与导入选项、同步间隔、安全上限与确认设置、通知以及登录相关选项。Google 客户端的选择会设为 `auto`，因此导入的自有客户端会被使用。旧的辅助程序路径会被丢弃——1.0 使用自带的已编译辅助程序。
3. 如果旧设置中没有代理，而旧的登录项设置了 `HTTPS_PROXY` 或 `HTTP_PROXY`，这个代理会成为 `proxy` 设置。
4. 在复制任何文件**之前**，先停止旧的后台任务（`launchctl bootout gui/<uid>/com.icloud-reminders-google-sync`），确保它的最后一轮不会在复制之后再写入；并把旧的 LaunchAgent plist 移到 `~/.config/local-tasks-bridge/backups/<时间>-migrate/`，让它不再在登录时启动。
5. 把 OAuth 客户端、令牌、同步对应关系和状态文件复制到 `~/.config/local-tasks-bridge/`，并设为私密权限。
6. 删除很早期的上游版本留在 `/tmp` 中、所有人都能读取的日志。

其他一切保持原样：旧的设置文件夹、程序文件和日志都不会被改动。

账号绑定会随同步对应关系一起带过来。早期版本的对应关系绑定的是那一次 Google 登录本身；在 1.0 的第一次同步中，桥接确认登录没有变化后，会就地把绑定升级为你的 Google 账号 ID。

## 用 App 导入

1. 安装 1.0（见 [README](../README.zh-CN.md#安装)）。安装脚本会识别 `~/Applications` 中试用版的同名 App，并把它以“Local Tasks Bridge (trial build …).app”的名字移到废纸篓。
2. 打开 Local Tasks Bridge。它会检测到早期安装，并提供**“导入我现有的设置”**。选择它并确认。
3. macOS 询问是否允许 Local Tasks Bridge 访问提醒事项时，点按“允许”。对 macOS 来说，1.0 与试用版的权限宿主是不同的 App，所以会重新请求权限。
4. 检查设置（见[检查结果](#检查结果)）。

## 用命令行导入

```bash
ltb migrate --dry-run   # 显示将导入哪些内容，不做任何更改
ltb migrate             # 先询问确认，然后导入
```

指定某一个安装：

```bash
ltb migrate --from ~/.config/icloud-reminders-google-sync/config.json
```

然后打开 Local Tasks Bridge，让后台同步开始运行。

## 检查结果

1. **状态：** 第一轮同步之后，`ltb status` 应显示 `healthy`。`ltb doctor` 会列出各项检查。
2. **试运行的结果应当几乎为空：**

   ```bash
   ltb sync --dry-run
   ```

   有少量更新是正常的。如果计划要创建或删除很多条目，请不要继续：选择“暂停同步”，然后查看 `ltb status` 和日志。
3. **旧的后台任务已经消失：**

   ```bash
   launchctl print gui/$(id -u)/com.icloud-reminders-google-sync
   ```

   应该提示找不到这个服务。
4. **你的设置原样带过来了**——用 `ltb config show` 或在“设置”中查看。试用版使用的值更严格（例如每轮最多只允许一个删除或完成，以及 `conflict_policy: skip`）。如果想改用 1.0 的默认值：

   ```bash
   echo '{"max_destructive_changes": 25, "max_destructive_ratio": 0.25,
          "conflict_policy": "newer_wins", "mutation_approval_prompt": true,
          "macos_notifications": true}' | ltb config merge --json
   ```

5. **做一次真实的往返测试：** 在 Mac 上修改一条测试用的提醒事项，在 Google 中修改一个测试任务，确认两边的改动都能到达对方。

### 通过 gcloud 登录的上游安装

如果上游安装是通过 gcloud 的应用默认凭据（`use_adc: true`）登录的，导入后仍会继续使用这些凭据。这种遗留方式能用，但 App 不支持。要换成正常的登录方式，请在 `~/.config/local-tasks-bridge/config.json` 中把 `use_adc` 设为 `false`，退出并重新打开 App，然后选择**“重新连接 Google…”**。由于旧的同步对应关系绑定的是 gcloud 凭据，桥接随后可能会提示*账号绑定已变化*；请让“重新连接 Google…”（或 `ltb rebuild`）重建对应关系——它会先备份，并且不删除任何内容（见[故障排除](troubleshooting.zh-CN.md#账号绑定已变化)）。

## 回退

旧文件没有被改动，旧的 LaunchAgent plist 也在备份文件夹中，所以你可以退回去：

1. 退出 Local Tasks Bridge（菜单 →“退出 Local Tasks Bridge”），并移除它的登录项：

   ```bash
   ltb agent uninstall --bootout
   ```

2. 恢复旧的登录项：

   ```bash
   mv ~/.config/local-tasks-bridge/backups/*-migrate/com.icloud-reminders-google-sync.plist \
      ~/Library/LaunchAgents/
   ```

3. **仅限试用版：** 试用版的登录项启动的是它的权限宿主 `~/Applications/Local Tasks Bridge.app/Contents/MacOS/LocalBridgeLauncher`，而它已被 1.0 的 App 替换。请先把 1.0 的 App 移到别处，再从废纸篓中取出“Local Tasks Bridge (trial build …).app”，改名为 `Local Tasks Bridge.app` 并放回 `~/Applications`。（也可以从试用版源码重新构建：提交 `b1c868a` 中的 `scripts/package-local-launcher.py`。）
4. 在让旧版本独自运行之前，先用旧引擎做一次试运行，看看它会做什么；Python 和文件路径请参照旧 LaunchAgent plist 中的写法：

   ```bash
   <旧的 python> ~/.local/share/icloud-reminders-google-sync/current/icloud_reminders_google_sync.py \
     --config <旧的设置文件> sync --dry-run --no-delete-stale
   ```

5. 重新启动它：

   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.icloud-reminders-google-sync.plist
   ```

1.0 运行期间所做的更改已经存在于“提醒事项”和 Google 中；旧引擎会通过同样的备注同步标记识别这些条目。切勿让新旧两个版本同时运行。

## 清理

在 1.0 稳定运行一段时间（比如一周）之后，你可以删除早期安装留下的东西：

- 旧的设置文件夹——`~/.config/reminders-task-bridge-trial/` 或 `~/.config/icloud-reminders-google-sync/`（其中有旧令牌和同步对应关系的私密副本）；
- 旧的程序文件 `~/.local/share/icloud-reminders-google-sync/`；
- 旧的日志 `~/Library/Logs/icloud-reminders-google-sync/`；
- 试用版：废纸篓中的试用版 App，以及它旧的提醒事项权限条目（`tccutil reset Reminders local.reminders.tasks.bridge`）；
- 上游：访达管理脚本 `~/Applications/Google Tasks ….command`，以及（如果你只为此使用 gcloud）它的凭据（`gcloud auth application-default revoke`）；
- `~/.config/local-tasks-bridge/backups/<时间>-migrate/` 中的旧 plist。

**不要在 Google 那边撤销旧的登录授权：** 1.0 现在用的正是同一个登录。
