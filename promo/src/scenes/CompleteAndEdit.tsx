import type React from "react";
import { Bridge } from "../components/Bridge";
import { SceneFrame } from "../components/SceneFrame";
import { SceneTitle } from "../components/SceneTitle";
import { TaskPanel, type RowState } from "../components/TaskPanel";
import { BRIDGE_WIDTH, TwoPanels } from "../components/TwoPanels";
import { getContent, type LangProps } from "../content";
import { useTimeline } from "../lib/progress";

export const COMPLETE_AND_EDIT_FRAMES = 210;

// A completion travels Reminders → Google Tasks, then a due-date change
// travels Google Tasks → Reminders.
export const CompleteAndEdit: React.FC<LangProps> = ({ lang }) => {
  const { ramp, flash, travel } = useTimeline();
  const content = getContent(lang);
  const t = content.completeAndEdit;
  const g = content.googleToReminders;
  const [passport, lunch, flights] = g.existing.concat(g.added);
  const card = content.remindersToGoogle.added;

  const rows = (side: "google" | "reminders"): RowState[] => {
    const google = side === "google";
    const doneAt = google ? 74 : 34;
    const dueAt = google ? 104 : 144;
    return [
      { id: "passport", ...passport },
      { id: "lunch", ...lunch, done: ramp(doneAt, doneAt + 12), highlight: flash(doneAt, doneAt + 40) },
      {
        id: "flights",
        ...flights,
        dueSwap: { to: t.newDue, progress: ramp(dueAt, dueAt + 12) },
        highlight: flash(dueAt, dueAt + 40),
      },
      { id: "card", ...card },
    ];
  };

  const toGoogle = travel(48, 74);
  const toReminders = travel(118, 144);

  return (
    <SceneFrame>
      <SceneTitle title={t.title} note={t.note} noteAt={160} />
      <TwoPanels
        left={
          <TaskPanel
            kind="google"
            heading={content.ui.googleTasks}
            listName={content.ui.myTasks}
            rows={rows("google")}
          />
        }
        bridge={
          <Bridge
            width={BRIDGE_WIDTH}
            pulse={toGoogle > 0 && toGoogle < 1 ? toGoogle : toReminders}
            direction={toGoogle < 1 ? "rtl" : "ltr"}
          />
        }
        right={
          <TaskPanel
            kind="reminders"
            heading={content.ui.reminders}
            listName={content.ui.remindersList}
            rows={rows("reminders")}
          />
        }
      />
    </SceneFrame>
  );
};
