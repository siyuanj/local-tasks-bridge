import type React from "react";
import { Bridge } from "../components/Bridge";
import { SceneFrame } from "../components/SceneFrame";
import { SceneTitle } from "../components/SceneTitle";
import { TaskPanel } from "../components/TaskPanel";
import { BRIDGE_WIDTH, TwoPanels } from "../components/TwoPanels";
import { getContent, type LangProps } from "../content";
import { useTimeline } from "../lib/progress";

export const GOOGLE_TO_REMINDERS_FRAMES = 210;

// A task typed into Google Tasks crosses the bridge and lands in Reminders.
export const GoogleToReminders: React.FC<LangProps> = ({ lang }) => {
  const { ramp, flash, travel } = useTimeline();
  const content = getContent(lang);
  const t = content.googleToReminders;
  const existing = t.existing.map((task, i) => ({ id: `t${i}`, ...task }));

  return (
    <SceneFrame>
      <SceneTitle title={t.title} note={t.note} noteAt={134} />
      <TwoPanels
        left={
          <TaskPanel
            kind="google"
            heading={content.ui.googleTasks}
            listName={content.ui.myTasks}
            rows={[
              ...existing,
              {
                id: "added",
                ...t.added,
                enter: ramp(46, 60),
                typed: travel(52, 86),
                highlight: flash(52, 110),
              },
            ]}
          />
        }
        bridge={
          <Bridge
            width={BRIDGE_WIDTH}
            connected={ramp(20, 40)}
            pulse={travel(92, 122)}
            direction="ltr"
          />
        }
        right={
          <TaskPanel
            kind="reminders"
            heading={content.ui.reminders}
            listName={content.ui.remindersList}
            rows={[
              ...existing,
              { id: "added", ...t.added, enter: ramp(120, 134), highlight: flash(120, 176) },
            ]}
          />
        }
      />
    </SceneFrame>
  );
};
