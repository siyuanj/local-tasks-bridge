import type { Content } from "./types";

export const zh: Content = {
  ui: {
    googleTasks: "Google Tasks",
    myTasks: "我的任务",
    reminders: "提醒事项",
    remindersList: "待办",
  },
  intro: {
    title: "Local Tasks Bridge",
    tagline: "让 Apple 提醒事项与 Google Tasks 在你的 Mac 上同步。",
  },
  twoPlaces: {
    title: "你的任务分散在两个地方。",
    note: "手机上用 Google Tasks，Mac 上用提醒事项。",
    googleTasks: [
      { title: "续签护照", due: "周一" },
      { title: "团队午餐", due: "今天" },
    ],
    reminders: [
      { title: "取干洗的衣服" },
      { title: "给牙医打电话", due: "明天" },
    ],
  },
  googleToReminders: {
    title: "在 Google Tasks 里加一个任务…",
    note: "…Mac 和 iPhone 的提醒事项里就有了。",
    existing: [
      { title: "续签护照", due: "周一" },
      { title: "团队午餐", due: "今天" },
    ],
    added: { title: "订去里斯本的机票", due: "周五" },
  },
  remindersToGoogle: {
    title: "…在提醒事项里加也行，Siri 也可以。",
    note: "它会马上同步到 Google Tasks。",
    added: { title: "买生日贺卡", due: "明天" },
  },
  completeAndEdit: {
    title: "勾掉它，改个日期。",
    note: "完成和修改都会双向同步。",
    newDue: "周六",
  },
  safetyReview: {
    title: "大批删除，等你确认。",
    note: "你确认之前，Google Tasks 里什么都不会删。",
    tasks: [
      { title: "续签护照" },
      { title: "团队午餐" },
      { title: "订去里斯本的机票" },
      { title: "买生日贺卡" },
      { title: "给花浇水" },
    ],
    sheetTitle: "30 项删除已暂缓",
    sheetBody: "一次消失的条目比平时多。",
    keep: "全部保留",
    review: "查看…",
  },
  privacy: {
    title: "中间没有任何服务器。",
    note: "你的 Mac 直接连接 Google，登录信息只留在你的 Mac 上。",
    mac: "你的 Mac",
    server: "第三方服务器",
  },
  menuBar: {
    title: "就在菜单栏里。",
    note: "几分钟就能设置好，随时立即同步或暂停。",
    clock: "周五 9:41",
    synced: "刚刚同步",
    syncing: "正在同步…",
    syncNow: "立即同步",
    pauseSync: "暂停同步",
    review: "查看待确认的更改…",
    settings: "设置…",
  },
  outro: {
    title: "Local Tasks Bridge",
    tagline: "免费开源 · 支持 macOS 13 及以上",
    url: "siyuanj.github.io/local-tasks-bridge",
  },
};
