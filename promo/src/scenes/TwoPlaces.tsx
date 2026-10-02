import type React from "react";
import { Bridge } from "../components/Bridge";
import { SceneFrame } from "../components/SceneFrame";
import { SceneTitle } from "../components/SceneTitle";
import { TaskPanel } from "../components/TaskPanel";
import { BRIDGE_WIDTH, TwoPanels } from "../components/TwoPanels";
import { getContent, type LangProps } from "../content";
import { useTimeline } from "../lib/progress";

export const TWO_PLACES_FRAMES = 150;

export const TwoPlaces: React.FC<LangProps> = ({ lang }) => {
  const { ramp } = useTimeline();
  const content = getContent(lang);
  const t = content.twoPlaces;
  const panelIn = ramp(38, 62);

  return (
    <SceneFrame>
      <SceneTitle title={t.title} note={t.note} moveAt={36} noteAt={64} />
      <TwoPanels
        left={
          <TaskPanel
            kind="google"
            heading={content.ui.googleTasks}
            listName={content.ui.myTasks}
            rows={t.googleTasks.map((task, i) => ({ id: `g${i}`, ...task }))}
            style={{ opacity: panelIn, translate: `${(panelIn - 1) * 120}px 0px` }}
          />
        }
        bridge={<Bridge width={BRIDGE_WIDTH} connected={0} style={{ opacity: ramp(62, 82) }} />}
        right={
          <TaskPanel
            kind="reminders"
            heading={content.ui.reminders}
            listName={content.ui.remindersList}
            rows={t.reminders.map((task, i) => ({ id: `r${i}`, ...task }))}
            style={{ opacity: panelIn, translate: `${(1 - panelIn) * 120}px 0px` }}
          />
        }
      />
    </SceneFrame>
  );
};
