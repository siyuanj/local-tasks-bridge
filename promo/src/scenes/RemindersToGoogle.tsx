import type React from "react";
import { Bridge } from "../components/Bridge";
import { SceneFrame } from "../components/SceneFrame";
import { SceneTitle } from "../components/SceneTitle";
import { TaskPanel } from "../components/TaskPanel";
import { BRIDGE_WIDTH, TwoPanels } from "../components/TwoPanels";
import { getContent, type LangProps } from "../content";
import { useTimeline } from "../lib/progress";

export const REMINDERS_TO_GOOGLE_FRAMES = 180;

// The reverse direction: added in Reminders (or with Siri), shows up in Google Tasks.
export const RemindersToGoogle: React.FC<LangProps> = ({ lang }) => {
  const { ramp, flash, travel } = useTimeline();
  const content = getContent(lang);
  const t = content.remindersToGoogle;
  const g = content.googleToReminders;
  const synced = [...g.existing, g.added].map((task, i) => ({ id: `t${i}`, ...task }));

  return (
    <SceneFrame>
      <SceneTitle title={t.title} note={t.note} noteAt={118} />
      <TwoPanels
        left={
          <TaskPanel
            kind="google"
            heading={content.ui.googleTasks}
            listName={content.ui.myTasks}
            rows={[
              ...synced,
              { id: "added", ...t.added, enter: ramp(108, 122), highlight: flash(108, 164) },
            ]}
          />
        }
        bridge={<Bridge width={BRIDGE_WIDTH} pulse={travel(82, 110)} direction="rtl" />}
        right={
          <TaskPanel
            kind="reminders"
            heading={content.ui.reminders}
            listName={content.ui.remindersList}
            rows={[
              ...synced,
              {
                id: "added",
                ...t.added,
                enter: ramp(40, 54),
                typed: travel(46, 76),
                highlight: flash(46, 100),
              },
            ]}
          />
        }
      />
    </SceneFrame>
  );
};
