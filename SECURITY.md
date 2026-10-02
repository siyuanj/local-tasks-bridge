# Security Policy

**English** · [简体中文](#安全政策简体中文)

## Supported versions

Security fixes are made for the **latest release** of Local Tasks Bridge and on
`main`. Older versions don't receive fixes; update with the installer, a new
download from Releases, or `git pull && make install`. Check your version with
`ltb version`.

| Version | Supported |
| --- | --- |
| Latest release (currently 1.0.x) | Yes |
| Earlier releases, the 2026-09 private trial, upstream `icloud-reminders-google-sync` | No — [migrate](docs/migration.md) to the latest release |

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** through GitHub:

**<https://github.com/siyuanj/local-tasks-bridge/security/advisories/new>**

Don't open a public issue, pull request or discussion for a suspected
vulnerability.

Examples of what we want to hear about:

- tokens, credentials or task content leaking — into other users' reach, logs,
  `status.json`, process arguments, notifications or the network;
- data being sent anywhere other than Apple Reminders on the Mac and Google's
  APIs;
- ways around the deletion safety limits, the approval flow, the empty-source
  guard or the account binding that could destroy or mix up data;
- weaknesses in the Google sign-in (PKCE, state validation, the loopback
  redirect) or in the handling of the OAuth client;
- problems with the installer, release artifacts, checksums, the login item or
  file permissions.

Out of scope: the “Google hasn't verified this app” warning and the Gatekeeper
prompt of the ad-hoc-signed 1.0 builds (both known and documented), and
problems in macOS, iCloud or Google's services themselves.

### What to include

- the version (`ltb version`), macOS version and Mac model (Apple silicon or
  Intel), and the sign-in method (shared or own client);
- a minimal reproduction using **synthetic** data — a test list with made-up
  items;
- the impact as you understand it, and a suggested fix if you have one.

### What to leave out or redact

Never include OAuth client secrets, access or refresh tokens, the contents of
`credentials.json`, `token.json` or `state.json`, Apple or Google account
identifiers, e-mail addresses, real reminder or task content, absolute paths
containing your user name, raw logs or exported data. `ltb doctor` output is
designed to be safe to share; still read it before you send it.

### What happens next

The maintainer will acknowledge the report, validate it privately, work on a
fix, and coordinate the release and disclosure with you. Reporters are credited
in the release notes unless they prefer otherwise.

---

## 安全政策（简体中文）

**支持的版本：** 只为 Local Tasks Bridge 的**最新发布版**和 `main` 分支提供安全修复。旧版本（包括 2026 年 9 月的私有试用版和上游的 `icloud-reminders-google-sync`）不再修复，请[迁移](docs/migration.zh-CN.md)到最新版本。用 `ltb version` 查看你的版本。

**报告漏洞：** 请通过 GitHub **私下**报告：

**<https://github.com/siyuanj/local-tasks-bridge/security/advisories/new>**

请不要为疑似漏洞公开提交问题、拉取请求或讨论。我们特别关心：令牌、凭据或任务内容的泄露；数据被发送到 Mac 上的“提醒事项”和 Google API 以外的地方；绕过删除安全上限、确认流程、空源保护或账号绑定的方法；Google 登录流程的弱点；以及安装脚本、发布文件、校验值、登录项或文件权限方面的问题。“Google 未验证此应用”警告和 1.0 临时签名带来的 Gatekeeper 提示属于已知情况，不在范围内。

**请提供：** 版本号（`ltb version`）、macOS 版本和 Mac 型号（Apple 芯片或 Intel）、登录方式（共享或自有客户端）、使用**合成数据**（测试列表和虚构条目）的最小复现步骤、你理解的影响，以及可能的修复建议。

**请删除或打码：** OAuth 客户端密钥、访问令牌和刷新令牌、`credentials.json`、`token.json`、`state.json` 的内容、Apple 或 Google 账号标识、邮箱地址、真实的提醒事项或任务内容、包含用户名的绝对路径、原始日志或导出的数据。`ltb doctor` 的输出在设计上可以安全分享，但发送前仍请自己检查一遍。

**后续流程：** 维护者会确认收到报告，私下验证，着手修复，并与你协调发布和披露的时间。除非你另有要求，发布说明中会致谢报告者。
