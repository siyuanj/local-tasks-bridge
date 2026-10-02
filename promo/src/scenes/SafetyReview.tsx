import type React from "react";
import { interpolate } from "remotion";
import { Bridge } from "../components/Bridge";
import { SceneFrame } from "../components/SceneFrame";
import { SceneTitle } from "../components/SceneTitle";
import { TaskPanel } from "../components/TaskPanel";
import { BRIDGE_WIDTH, TwoPanels } from "../components/TwoPanels";
import { getContent, type LangProps } from "../content";
import { useTimeline } from "../lib/progress";
import { CLAMP, COLORS, EASE, SHADOW } from "../theme";

export const SAFETY_REVIEW_FRAMES = 240;

const SHEET_WIDTH = 1080;

// Reminders empties out at once; the bridge holds the deletions and asks
// before anything is removed from Google Tasks.
export const SafetyReview: React.FC<LangProps> = ({ lang }) => {
  const { frame, ramp } = useTimeline();
  const content = getContent(lang);
  const t = content.safetyReview;
  const sheetIn = ramp(104, 126);

  return (
    <SceneFrame>
      <TwoPanels
        left={
          <TaskPanel
            kind="google"
            heading={content.ui.googleTasks}
            listName={content.ui.myTasks}
            rows={t.tasks.map((task, i) => ({ id: `t${i}`, ...task }))}
          />
        }
        bridge={<Bridge width={BRIDGE_WIDTH} held={ramp(82, 98)} />}
        right={
          <TaskPanel
            kind="reminders"
            heading={content.ui.reminders}
            listName={content.ui.remindersList}
            rows={t.tasks.map((task, i) => ({
              id: `t${i}`,
              ...task,
              enter: 1 - ramp(34 + i * 6, 46 + i * 6, EASE.accelerate),
            }))}
          />
        }
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundColor: "white",
          opacity: sheetIn * 0.6,
        }}
      />
      {/* Above the scrim, so the headline stays sharp while the sheet is up. */}
      <SceneTitle title={t.title} note={t.note} noteAt={150} />
      <div
        style={{
          position: "absolute",
          left: (1920 - SHEET_WIDTH) / 2,
          width: SHEET_WIDTH,
          bottom: 110,
          boxSizing: "border-box",
          padding: "40px 48px 36px",
          borderRadius: 32,
          backgroundColor: COLORS.canvas,
          boxShadow: `${SHADOW}, 0 30px 80px rgba(60, 64, 67, 0.18)`,
          opacity: sheetIn,
          translate: interpolate(frame, [104, 126], ["0px 80px", "0px 0px"], {
            ...CLAMP,
            easing: EASE.decelerate,
          }),
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 32 }}>
          <div
            style={{
              width: 88,
              height: 88,
              flexShrink: 0,
              borderRadius: "50%",
              backgroundColor: COLORS.yellow,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 11,
            }}
          >
            <div style={{ width: 11, height: 36, borderRadius: 4, backgroundColor: COLORS.ink }} />
            <div style={{ width: 11, height: 36, borderRadius: 4, backgroundColor: COLORS.ink }} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 48, fontWeight: 700 }}>{t.sheetTitle}</div>
            <div style={{ fontSize: 34, fontWeight: 500, color: COLORS.inkSoft, marginTop: 4 }}>
              {t.sheetBody}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 18, marginTop: 28 }}>
          <Button label={t.keep} />
          <Button label={t.review} filled />
        </div>
      </div>
    </SceneFrame>
  );
};

const Button: React.FC<{ readonly label: string; readonly filled?: boolean }> = ({
  label,
  filled = false,
}) => (
  <div
    style={{
      fontSize: 30,
      fontWeight: 500,
      textAlign: "center",
      padding: "14px 34px",
      borderRadius: 999,
      color: filled ? "white" : COLORS.blue,
      backgroundColor: filled ? COLORS.blue : "transparent",
      border: filled ? `2px solid ${COLORS.blue}` : `2px solid ${COLORS.outline}`,
    }}
  >
    {label}
  </div>
);
