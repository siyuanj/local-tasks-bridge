# Local trial status

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
