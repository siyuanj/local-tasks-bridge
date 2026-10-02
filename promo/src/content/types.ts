export type Lang = "en" | "zh";

export type DemoTask = {
  readonly title: string;
  readonly due?: string;
};

// Every on-screen word lives here, one file per language. Adding a scene means
// adding its entry to this type; TypeScript then requires it in en.ts and zh.ts.
export type Content = {
  readonly ui: {
    readonly googleTasks: string;
    readonly myTasks: string;
    readonly reminders: string;
    readonly remindersList: string;
  };
  readonly intro: { readonly title: string; readonly tagline: string };
  readonly twoPlaces: {
    readonly title: string;
    readonly note: string;
    readonly googleTasks: readonly DemoTask[];
    readonly reminders: readonly DemoTask[];
  };
  readonly googleToReminders: {
    readonly title: string;
    readonly note: string;
    readonly existing: readonly DemoTask[];
    readonly added: DemoTask;
  };
  readonly remindersToGoogle: {
    readonly title: string;
    readonly note: string;
    readonly added: DemoTask;
  };
  readonly completeAndEdit: {
    readonly title: string;
    readonly note: string;
    readonly newDue: string;
  };
  readonly safetyReview: {
    readonly title: string;
    readonly note: string;
    readonly tasks: readonly DemoTask[];
    readonly sheetTitle: string;
    readonly sheetBody: string;
    readonly keep: string;
    readonly review: string;
  };
  readonly privacy: {
    readonly title: string;
    readonly note: string;
    readonly mac: string;
    readonly server: string;
  };
  readonly menuBar: {
    readonly title: string;
    readonly note: string;
    readonly clock: string;
    readonly synced: string;
    readonly syncing: string;
    readonly syncNow: string;
    readonly pauseSync: string;
    readonly review: string;
    readonly settings: string;
  };
  readonly outro: {
    readonly title: string;
    readonly tagline: string;
    readonly url: string;
  };
};
