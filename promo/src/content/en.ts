import type { Content } from "./types";

export const en: Content = {
  ui: {
    googleTasks: "Google Tasks",
    myTasks: "My Tasks",
    reminders: "Reminders",
    remindersList: "Errands",
  },
  intro: {
    title: "Local Tasks Bridge",
    tagline: "Apple Reminders and Google Tasks, in sync on your Mac.",
  },
  twoPlaces: {
    title: "Your tasks live in two places.",
    note: "Google Tasks on your phone. Reminders on your Mac.",
    googleTasks: [
      { title: "Renew passport", due: "Mon" },
      { title: "Team lunch", due: "Today" },
    ],
    reminders: [
      { title: "Pick up dry cleaning" },
      { title: "Call the dentist", due: "Tomorrow" },
    ],
  },
  googleToReminders: {
    title: "Add a task in Google Tasks…",
    note: "…and it’s in Reminders on your Mac and iPhone.",
    existing: [
      { title: "Renew passport", due: "Mon" },
      { title: "Team lunch", due: "Today" },
    ],
    added: { title: "Book flights to Lisbon", due: "Fri" },
  },
  remindersToGoogle: {
    title: "…or in Reminders, even with Siri.",
    note: "It syncs to Google Tasks right away.",
    added: { title: "Buy birthday card", due: "Tomorrow" },
  },
  completeAndEdit: {
    title: "Check it off. Change the date.",
    note: "Completions and edits sync both ways.",
    newDue: "Sat",
  },
  safetyReview: {
    title: "Big deletions wait for your OK.",
    note: "Nothing is removed from Google Tasks until you review it.",
    tasks: [
      { title: "Renew passport" },
      { title: "Team lunch" },
      { title: "Book flights to Lisbon" },
      { title: "Buy birthday card" },
      { title: "Water the plants" },
    ],
    sheetTitle: "30 deletions are on hold",
    sheetBody: "More than usual disappeared at once.",
    keep: "Keep Them",
    review: "Review…",
  },
  privacy: {
    title: "No servers in between.",
    note: "Your Mac talks to Google directly. Your sign-in stays on your Mac.",
    mac: "Your Mac",
    server: "Third-party server",
  },
  menuBar: {
    title: "Lives in your menu bar.",
    note: "Set up in minutes. Sync now or pause any time.",
    clock: "Fri 9:41",
    synced: "Last synced just now",
    syncing: "Syncing…",
    syncNow: "Sync Now",
    pauseSync: "Pause Sync",
    review: "Review Pending Changes…",
    settings: "Settings…",
  },
  outro: {
    title: "Local Tasks Bridge",
    tagline: "Free and open source · macOS 13 or later",
    url: "siyuanj.github.io/local-tasks-bridge",
  },
};
