import type React from "react";
import { Img, interpolate, interpolateColors, staticFile } from "remotion";
import { SceneFrame } from "../components/SceneFrame";
import { SceneTitle } from "../components/SceneTitle";
import { getContent, type Content, type LangProps } from "../content";
import { useTimeline } from "../lib/progress";
import { CLAMP, COLORS, EASE, SHADOW, WIDTH } from "../theme";

export const MENU_BAR_FRAMES = 180;

const BAR = { width: 1500, height: 64, top: 330 };
const ICON = 34;
const MENU_WIDTH = 560;
const ROW_HEIGHT = 62;
const DIVIDER_HEIGHT = 18; // 2 px line with 8 px above and below
const ROW_FONT = 34;

// Sync Now is clicked at CLICK_AT; the status shows "Syncing…" until SYNCED_AT.
const CLICK_AT = 100;
const SYNCED_AT = 125;

export const MenuBar: React.FC<LangProps> = ({ lang }) => {
  const { frame, ramp } = useTimeline();
  const t = getContent(lang).menuBar;
  const barIn = ramp(24, 44);
  const hover = ramp(80, 92);
  // The selection slides onto Sync Now, blinks off on the click, then lets go.
  const selected =
    hover *
    (1 - interpolate(frame, [CLICK_AT, CLICK_AT + 2, CLICK_AT + 5, CLICK_AT + 7], [0, 1, 1, 0], CLAMP)) *
    (1 - ramp(112, 124));

  return (
    <SceneFrame>
      <SceneTitle title={t.title} note={t.note} moveAt={20} noteAt={125} />
      <div
        style={{
          position: "absolute",
          top: BAR.top,
          left: (WIDTH - BAR.width) / 2,
          width: BAR.width,
          height: BAR.height,
          padding: "0 34px",
          boxSizing: "border-box",
          borderRadius: 16,
          backgroundColor: COLORS.canvas,
          boxShadow: "0 1px 2px rgba(60, 64, 67, 0.10), 0 6px 24px rgba(60, 64, 67, 0.12)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          opacity: barIn,
          translate: `0px ${(barIn - 1) * 24}px`,
        }}
      >
        <MenuPlaceholders />
        <div style={{ display: "flex", alignItems: "center", gap: 32 }}>
          <div style={{ position: "relative", width: ICON, height: ICON }}>
            <div
              style={{
                position: "absolute",
                inset: "-8px -11px",
                borderRadius: 10,
                backgroundColor: "rgba(31, 31, 31, 0.09)",
                opacity: ramp(38, 44),
              }}
            />
            <Img
              src={staticFile("icon.png")}
              style={{ position: "relative", width: ICON, height: ICON, borderRadius: 8 }}
            />
            <Dropdown
              t={t}
              syncing={frame >= CLICK_AT && frame < SYNCED_AT}
              pulse={frame - CLICK_AT}
              selected={selected}
              slide={hover}
              style={{
                position: "absolute",
                top: ICON + (BAR.height - ICON) / 2 + 10,
                right: -26,
                transformOrigin: "100% 0%",
                opacity: interpolate(frame, [46, 54], [0, 1], CLAMP),
                scale: interpolate(frame, [46, 62], [0.85, 1], {
                  ...CLAMP,
                  easing: EASE.decelerate,
                  output: "perceptual-scale",
                }),
              }}
            />
          </div>
          <WifiGlyph />
          <div style={{ fontSize: 30, fontWeight: 500, whiteSpace: "nowrap" }}>{t.clock}</div>
        </div>
      </div>
    </SceneFrame>
  );
};

const Dropdown: React.FC<{
  readonly t: Content["menuBar"];
  readonly syncing: boolean;
  readonly pulse: number; // frames since the click
  readonly selected: number;
  readonly slide: number;
  readonly style?: React.CSSProperties;
}> = ({ t, syncing, pulse, selected, slide, style }) => (
  <div
    style={{
      width: MENU_WIDTH,
      padding: 12,
      boxSizing: "border-box",
      borderRadius: 18,
      backgroundColor: COLORS.canvas,
      boxShadow: SHADOW,
      ...style,
    }}
  >
    <div style={{ position: "relative" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: ROW_HEIGHT + DIVIDER_HEIGHT,
          height: ROW_HEIGHT,
          borderRadius: 10,
          backgroundColor: COLORS.blue,
          opacity: selected,
          translate: `0px ${(slide - 1) * 30}px`,
        }}
      />
      <div style={{ ...rowStyle, gap: 16 }}>
        <div
          style={{
            width: 14,
            height: 14,
            borderRadius: "50%",
            backgroundColor: COLORS.green,
            scale: String(syncing ? 1 + 0.4 * Math.abs(Math.sin(pulse * 0.25)) : 1),
          }}
        />
        <div style={{ fontSize: 30, fontWeight: 500, color: COLORS.inkSoft }}>
          {syncing ? t.syncing : t.synced}
        </div>
      </div>
      <Divider />
      <div
        style={{
          ...rowStyle,
          color: interpolateColors(selected, [0, 1], [COLORS.ink, COLORS.canvas]),
        }}
      >
        {t.syncNow}
      </div>
      <div style={rowStyle}>{t.pauseSync}</div>
      <div style={rowStyle}>{t.review}</div>
      <Divider />
      <div style={rowStyle}>{t.settings}</div>
    </div>
  </div>
);

const rowStyle: React.CSSProperties = {
  position: "relative",
  height: ROW_HEIGHT,
  padding: "0 22px",
  display: "flex",
  alignItems: "center",
  fontSize: ROW_FONT,
  fontWeight: 500,
  whiteSpace: "nowrap",
};

const Divider: React.FC = () => (
  <div
    style={{
      height: 2,
      margin: `${(DIVIDER_HEIGHT - 2) / 2}px 22px`,
      backgroundColor: COLORS.outline,
    }}
  />
);

// Neutral stand-ins for the frontmost app's menus on the left of the bar.
const MenuPlaceholders: React.FC = () => (
  <div style={{ display: "flex", alignItems: "center", gap: 34 }}>
    {[72, 52, 56, 64].map((width, i) => (
      <div
        key={width}
        style={{
          width,
          height: 14,
          borderRadius: 7,
          backgroundColor: i === 0 ? COLORS.inkFaint : COLORS.outline,
        }}
      />
    ))}
  </div>
);

const WifiGlyph: React.FC = () => (
  <svg width="34" height="26" viewBox="0 0 34 26">
    {[16, 10.5, 5].map((r) => (
      <path
        key={r}
        d={`M ${17 - r * 0.7071} ${23 - r * 0.7071} A ${r} ${r} 0 0 1 ${17 + r * 0.7071} ${23 - r * 0.7071}`}
        fill="none"
        stroke={COLORS.ink}
        strokeWidth="3.2"
        strokeLinecap="round"
      />
    ))}
    <circle cx="17" cy="23" r="2.4" fill={COLORS.ink} />
  </svg>
);
