# 创建你自己的 Google Cloud 客户端

[English](google-cloud-setup.md) · **简体中文**

除了发布版内置的共享客户端，Local Tasks Bridge 也可以用**你自己的 OAuth 客户端**登录 Google。以下情况需要这样做：

- 你是从源码构建的 App（源码构建不包含共享客户端）；
- 你希望独享每天 50,000 次的 Google Tasks 配额，并使用 1 分钟的默认同步间隔；
- 共享客户端暂时不可用，例如已达到 Google 对未验证应用的 100 位用户上限；
- 你的 Google Workspace（公司或学校）账号不允许使用共享客户端。

整个过程大约十分钟，完全免费，不需要绑定结算账号。你将会：创建一个 Google Cloud 项目，启用 Google Tasks API，向 Google 描述你的应用并发布它，创建一个类型为**桌面应用（Desktop app）**的客户端，下载它的 JSON 文件，最后把这个文件导入 Local Tasks Bridge。

以下步骤基于目前的 Google Cloud 控制台，OAuth 相关设置位于 **Google Auth Platform** 之下。为了方便对照，下文同时给出英文界面名称和中文界面中的大致名称（中文翻译可能与实际略有出入）；每一步给出的网址是准确的，可以直接打开。

> [!TIP]
> 在中国大陆，需要先让浏览器能访问 Google（例如开启代理），才能打开下面的控制台页面。

## 1. 创建项目

1. 打开 <https://console.cloud.google.com/projectcreate> 并登录。最简单的做法是使用你要同步的那个 Google 账号，不过用其他账号也可以。
2. **Project name（项目名称）：** 例如 `Local Tasks Bridge`。个人 Gmail 账号的 **Location（位置）** 保持 **No organization（无组织）** 即可。
3. 点按 **Create（创建）**，然后确认页面顶部的项目选择器中已经选中了这个新项目。

## 2. 启用 Google Tasks API

1. 打开 <https://console.cloud.google.com/apis/library/tasks.googleapis.com>。
2. 确认选中的是刚才的新项目，然后点按 **Enable（启用）**。

## 3. 描述你的应用（Branding）

1. 打开 <https://console.cloud.google.com/auth/overview>。如果页面提示 Google Auth Platform 尚未配置，点按 **Get started（开始）**：
   - **App information（应用信息）：** **App name（应用名称）** 可填 `Local Tasks Bridge (personal)`，**User support email（用户支持电子邮件）** 填你的邮箱。点按 **Next（下一步）**。
   - **Audience（目标对象）：** 选择 **External（外部）**（**Internal（内部）** 的情况见 [Workspace 账号](#google-workspace-账号)）。点按 **Next**。
   - **Contact information（联系信息）：** 填你的邮箱。点按 **Next**。
   - **Finish（完成）：** 同意《Google API Services: User Data Policy》（Google API 服务用户数据政策），点按 **Continue（继续）**，再点按 **Create（创建）**。
2. 打开 **Branding（品牌塑造）**（<https://console.cloud.google.com/auth/branding>），核对应用名称和支持邮箱。不要上传徽标：添加徽标会让应用需要经过 Google 的品牌验证。
3. 如果下一步中的 **Publish app（发布应用）** 按钮一直是灰色，说明 Google 要求先提供应用的公开页面。请在 **App domain（应用网域）** 和 **Authorized domains（已获授权的网域）** 中填写：
   - **Application home page（应用首页）：** `https://siyuanj.github.io/local-tasks-bridge-site/`
   - **Application privacy policy link（应用隐私权政策链接）：** `https://siyuanj.github.io/local-tasks-bridge-site/privacy/`
   - **Authorized domain（已获授权的网域）：** `siyuanj.github.io`

   这是本项目介绍这款纯本地软件的公开页面，对你个人的客户端同样适用；你也可以换成自己的页面。最后点按 **Save（保存）**。

## 4. 发布应用（Audience）

1. 打开 **Audience（目标对象）**（<https://console.cloud.google.com/auth/audience>）。
2. **Publishing status（发布状态）** 显示为 **Testing（测试）**。点按 **Publish app（发布应用）** 并确认，状态会变为 **In production（正式版）**。

为什么要发布？应用处于 **Testing** 状态时，Google 只允许名单中的测试用户登录，并且**会在 7 天后让登录失效**，桥接每周都会停一次。发布为正式版后，登录会一直有效，直到你主动撤销（如果某个登录大约六个月没有被使用，Google 仍可能让它过期）。

发布并不会公开你的任务，也不会把你的应用列在任何地方。你的应用仍然是**未经验证**的：登录时 Google 会显示**“Google 未验证此应用”（Google hasn't verified this app）**。点按 **“高级”（Advanced）**，再点按 **“转至 *你的应用名称*（不安全）”**。对你自己创建的客户端来说这完全正常——你本人就是它的开发者。只有当应用的用户超过 100 人时，Google 才要求验证；个人客户端不需要。

## 5. 数据访问（Data Access，可选）

这一步可以跳过：Local Tasks Bridge 会在你登录时只申请它需要的权限范围。如果你仍希望在控制台中列出它们，请打开 **Data Access（数据访问）**（<https://console.cloud.google.com/auth/scopes>），点按 **Add or remove scopes（添加或移除范围）**，然后选择：

| 权限范围 | 用途 |
| --- | --- |
| `https://www.googleapis.com/auth/tasks` | 读写你的任务列表和任务 |
| `openid` | 识别 Google 账号，让同步对应关系与该账号绑定 |
| `https://www.googleapis.com/auth/userinfo.email`（`email`） | 显示当前连接的是哪个账号 |

点按 **Update（更新）**，再点按 **Save（保存）**。桥接不会申请其他任何权限——不涉及 Gmail、日历、云端硬盘或 Cloud 资源。

## 6. 创建“桌面应用”客户端

1. 打开 **Clients（客户端）**（<https://console.cloud.google.com/auth/clients>），点按 **Create client（创建客户端）**。
2. **Application type（应用类型）：** 选择 **Desktop app（桌面应用）**。其他类型（例如 **Web application（Web 应用）**）无法用于桥接的登录方式，导入时会被拒绝。
3. **Name（名称）：** 随意，例如 `Local Tasks Bridge – my Mac`。点按 **Create（创建）**。
4. 在 **OAuth client created（已创建 OAuth 客户端）** 对话框中，点按 **Download JSON（下载 JSON）**。文件会保存到“下载”文件夹，文件名类似 `client_secret_123456789012-abc….apps.googleusercontent.com.json`。

请马上下载：Google 只在创建客户端时显示客户端密钥。如果文件丢了，可以在 **Clients** 中打开这个客户端添加新的密钥，或者干脆新建一个客户端。

请把这个文件当作私密文件：不要通过邮件发送、不要贴到聊天中，也不要提交到 Git 仓库。

## 7. 把客户端导入 Local Tasks Bridge

- **在 App 中：** 在设置向导中选择“使用我自己的 Google Cloud OAuth 客户端（高级，无用户数限制）”，然后点按“选择客户端 JSON…”；之后也可以在“设置…”→“Google”中使用“导入客户端 JSON…”。
- **在“终端”中：**

  ```bash
  ltb client import ~/Downloads/client_secret_*.apps.googleusercontent.com.json
  ```

桥接会检查这个文件是否属于**桌面应用**客户端，把它复制到 `~/.config/local-tasks-bridge/credentials.json`（只有你能读取），并切换为使用它（`oauth_client` 变为 `custom`）。之后可以删除“下载”文件夹中的那份。用 `ltb client status` 可以查看结果。

然后登录：继续设置向导，或在 App 中选择**“重新连接 Google…”**，或运行 `ltb auth`。浏览器会打开 Google 登录页面：

1. 选择你的账号。
2. 看到**“Google 未验证此应用”**时，点按**“高级”**→**“转至……（不安全）”**。
3. 保持勾选**“创建、修改、整理和删除你的所有任务”**，点按**“继续”**。
4. 浏览器显示**“已收到 Google 授权”**后，回到 App 即可。

登录过程最多等待五分钟。

### 从共享客户端切换过来

按上面的方法导入你自己的客户端，然后用**同一个 Google 账号**重新登录。同步对应关系绑定的是你的 Google 账号 ID，而不是客户端，所以它会被保留，同步从上次的位置继续。自有客户端的默认同步间隔是 1 分钟，可以在“设置”中修改（见[配置说明](configuration.zh-CN.md#同步间隔与-google-配额)）。

## Google Workspace 账号

如果你的 Google 账号属于公司、学校或大学，由管理员决定哪些第三方应用可以访问 Google 数据：

- 如果登录时出现 **“Access blocked”（已屏蔽访问）**、`admin_policy_enforced`，或提示你的机构需要审核此应用，请让管理员信任你的客户端 ID（管理控制台 → **安全性 → 访问权限和数据控制 → API 控制 → 管理第三方应用访问权限**），或者改用个人 Google 账号。
- 如果你在所属组织内创建项目，可以把目标对象设为 **Internal（内部）**。内部应用只能由该组织的账号使用，但不需要验证、不会显示“未验证”警告，也没有 7 天的限制。组织外的账号登录时会看到 `org_internal` 错误。

## 常见错误

| 看到的现象 | 原因 | 解决办法 |
| --- | --- | --- |
| `Error 403: access_denied`，并提示“…… has not completed the Google verification process”（尚未完成 Google 验证流程） | 应用仍处于 **Testing** 状态，而你的账号不在测试用户名单中 | [发布应用](#4-发布应用audience)，或在 **Audience → Test users（测试用户）** 中添加你自己 |
| 刚点了“取消”就出现 `access_denied` | 你拒绝了授权 | 重新登录 |
| `Error 400: redirect_uri_mismatch` | 客户端类型是 **Web 应用** | 创建**桌面应用**客户端并导入其 JSON；桥接在导入时就会拒绝 Web 客户端 |
| `Error 401: invalid_client` 或 `deleted_client` | 客户端已被删除，或密钥已被重置 | 重新下载 JSON（或新建客户端）并导入 |
| “This app is blocked”（此应用已被屏蔽） | Google 拦截了这次登录——常见于加入了 Google 高级保护计划的账号，或受 Workspace 政策限制 | 改用未开启高级保护的个人账号，或联系管理员 |
| `admin_policy_enforced`，或“Access blocked: …… admin” | Workspace 政策 | 见 [Workspace 账号](#google-workspace-账号) |
| `org_internal` | 应用是 **Internal（内部）**，而你用的是组织外的账号 | 改用该组织的账号，或把目标对象改为 **External（外部）** |
| App 提示 Google 没有授予 Google Tasks 权限 | 授权页面上取消勾选了任务权限 | 重新登录并保持勾选；桥接会立即拒绝缺少该权限的登录 |
| 每周都要重新登录一次 | 应用仍处于 **Testing** 状态 | [发布应用](#4-发布应用audience)，然后再登录一次 |
| 日志中出现 “Google Tasks API has not been used in project … or it is disabled” | 该项目没有启用这个 API | [启用 API](#2-启用-google-tasks-api)，等几分钟再试 |
| 之后某天提示“登录已过期或被撤销” | 令牌被撤销（例如在 <https://myaccount.google.com/permissions> 中）或已过期 | 选择**“重新连接 Google…”**，或运行 `ltb auth` |
| 浏览器完全打不开 Google | 无法连接 Google（在中国大陆很常见） | 配置代理，见[网络与代理](troubleshooting.zh-CN.md#网络与代理) |

更多帮助见 [troubleshooting.zh-CN.md](troubleshooting.zh-CN.md)。
