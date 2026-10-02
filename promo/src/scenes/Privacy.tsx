import type React from "react";
import { interpolate } from "remotion";
import { AppIcon } from "../components/Brand";
import { SceneFrame } from "../components/SceneFrame";
import { SceneTitle } from "../components/SceneTitle";
import { getContent, type LangProps } from "../content";
import { useTimeline } from "../lib/progress";
import { CLAMP, COLORS, SHADOW, TYPE, WIDTH } from "../theme";

export const PRIVACY_FRAMES = 180;

// Layout in px. The Mac's screen and both tiles share one horizontal centre line.
const SERVER = { width: 520, height: 108, top: 392 };
const SCREEN = { width: 400, height: 260, top: 550 };
const BASE_WIDTH = 500;
const CENTER_Y = SCREEN.top + SCREEN.height / 2;
const TILE = { width: 300, height: 250, inset: 220 };

// Data dots run along each line in both directions, one each way per loop.
const FLOW = { start: 50, end: 170, period: 40 };

export const Privacy: React.FC<LangProps> = ({ lang }) => {
  const { ramp } = useTimeline();
  const content = getContent(lang);
  const t = content.privacy;
  const tilesIn = ramp(28, 50);

  return (
    <SceneFrame>
      <SceneTitle title={t.title} note={t.note} moveAt={20} noteAt={95} />
      <Server label={t.server} enter={ramp(35, 50)} strike={ramp(60, 75)} fade={ramp(72, 90)} />
      <FlowLine
        from={TILE.inset + TILE.width}
        to={WIDTH / 2 - SCREEN.width / 2}
        color={COLORS.remindersOrange}
        halo="rgba(255, 149, 0, 0.16)"
      />
      <FlowLine
        from={WIDTH - TILE.inset - TILE.width}
        to={WIDTH / 2 + SCREEN.width / 2}
        color={COLORS.blue}
        halo="rgba(66, 133, 244, 0.16)"
      />
      <Laptop label={t.mac} enter={ramp(22, 44)} />
      <Tile side="left" label={content.ui.reminders} enter={tilesIn}>
        <RemindersGlyph />
      </Tile>
      <Tile side="right" label={content.ui.googleTasks} enter={tilesIn}>
        <GoogleGlyph />
      </Tile>
    </SceneFrame>
  );
};

const Laptop: React.FC<{ readonly label: string; readonly enter: number }> = ({
  label,
  enter,
}) => (
  <div
    style={{
      position: "absolute",
      top: SCREEN.top,
      left: WIDTH / 2 - BASE_WIDTH / 2,
      width: BASE_WIDTH,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      opacity: enter,
      transformOrigin: "50% 100%",
      scale: interpolate(enter, [0, 1], [0.9, 1], { ...CLAMP, output: "perceptual-scale" }),
    }}
  >
    <div
      style={{
        width: SCREEN.width,
        height: SCREEN.height,
        padding: 14,
        boxSizing: "border-box",
        borderRadius: 26,
        backgroundColor: "#3C4043",
        boxShadow: SHADOW,
      }}
    >
      <div
        style={{
          width: "100%",
          height: "100%",
          borderRadius: 14,
          backgroundColor: COLORS.surface,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon size={116} at={34} />
      </div>
    </div>
    <div
      style={{
        position: "relative",
        width: BASE_WIDTH,
        height: 22,
        borderRadius: "4px 4px 14px 14px",
        backgroundColor: "#D5D8DC",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 0,
          left: BASE_WIDTH / 2 - 50,
          width: 100,
          height: 8,
          borderRadius: "0 0 8px 8px",
          backgroundColor: "#BDC1C6",
        }}
      />
    </div>
    <div style={{ marginTop: 26, fontSize: 40, fontWeight: 500 }}>{label}</div>
  </div>
);

const Tile: React.FC<{
  readonly side: "left" | "right";
  readonly label: string;
  readonly enter: number;
  readonly children: React.ReactNode;
}> = ({ side, label, enter, children }) => (
  <div
    style={{
      position: "absolute",
      top: CENTER_Y - TILE.height / 2,
      left: side === "left" ? TILE.inset : WIDTH - TILE.inset - TILE.width,
      width: TILE.width,
      height: TILE.height,
      borderRadius: 32,
      backgroundColor: COLORS.canvas,
      boxShadow: SHADOW,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 26,
      opacity: enter,
      translate: `${(side === "left" ? -1 : 1) * (1 - enter) * 80}px 0px`,
    }}
  >
    {children}
    <div style={{ fontSize: TYPE.ui, fontWeight: 500, whiteSpace: "nowrap" }}>{label}</div>
  </div>
);

// A solid line from a tile to the Mac that draws outward from the Mac, then
// carries dots both ways.
const FlowLine: React.FC<{
  readonly from: number; // x at the tile
  readonly to: number; // x at the Mac
  readonly color: string;
  readonly halo: string;
}> = ({ from, to, color, halo }) => {
  const { frame, ramp } = useTimeline();
  const visible = interpolate(
    frame,
    [FLOW.start, FLOW.start + 8, FLOW.end - 8, FLOW.end],
    [0, 1, 1, 0],
    CLAMP,
  );

  return (
    <>
      <div
        style={{
          position: "absolute",
          top: CENTER_Y - 3,
          left: Math.min(from, to),
          width: Math.abs(to - from),
          height: 6,
          borderRadius: 3,
          backgroundColor: COLORS.outline,
          transformOrigin: to > from ? "100% 50%" : "0% 50%",
          scale: `${ramp(42, 56)} 1`,
        }}
      />
      {[0, 0.5].map((offset, i) => {
        const loop = ((((frame - FLOW.start) / FLOW.period + offset) % 1) + 1) % 1;
        // The first dot travels tile → Mac, the second Mac → tile.
        const position = i === 0 ? loop : 1 - loop;

        return (
          <div
            key={offset}
            style={{
              position: "absolute",
              top: CENTER_Y - 9,
              left: from + (to - from) * position - 9,
              width: 18,
              height: 18,
              borderRadius: "50%",
              backgroundColor: color,
              boxShadow: `0 0 0 8px ${halo}`,
              opacity: visible * interpolate(loop, [0, 0.15, 0.85, 1], [0, 1, 1, 0], CLAMP),
            }}
          />
        );
      })}
    </>
  );
};

// The middleman other sync services use: shown, then struck out.
const Server: React.FC<{
  readonly label: string;
  readonly enter: number;
  readonly strike: number;
  readonly fade: number;
}> = ({ label, enter, strike, fade }) => (
  <div
    style={{
      position: "absolute",
      top: SERVER.top,
      left: WIDTH / 2 - SERVER.width / 2,
      width: SERVER.width,
      height: SERVER.height,
      translate: `0px ${(1 - enter) * 20}px`,
    }}
  >
    <div
      style={{
        width: "100%",
        height: "100%",
        boxSizing: "border-box",
        border: `3px dashed ${COLORS.inkFaint}`,
        borderRadius: 26,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 22,
        opacity: enter * (1 - 0.75 * fade),
      }}
    >
      <ServerGlyph />
      <div
        style={{ fontSize: 36, fontWeight: 500, color: COLORS.inkSoft, whiteSpace: "nowrap" }}
      >
        {label}
      </div>
    </div>
    <svg
      width={SERVER.width + 48}
      height={SERVER.height + 32}
      style={{ position: "absolute", left: -24, top: -16, overflow: "visible" }}
    >
      <line
        x1={12}
        y1={SERVER.height + 22}
        x2={SERVER.width + 36}
        y2={10}
        stroke={COLORS.red}
        strokeWidth={8}
        strokeLinecap="round"
        pathLength={1}
        strokeDasharray="1 1"
        strokeDashoffset={1 - strike}
        opacity={interpolate(strike, [0, 0.02], [0, 1], CLAMP)}
      />
    </svg>
  </div>
);

const ServerGlyph: React.FC = () => (
  <svg width="46" height="50" viewBox="0 0 46 50">
    {[2, 18.5, 35].map((y) => (
      <g key={y}>
        <rect
          x="2"
          y={y}
          width="42"
          height="13"
          rx="4"
          fill="none"
          stroke={COLORS.inkFaint}
          strokeWidth="3"
        />
        <circle cx="10" cy={y + 6.5} r="2.2" fill={COLORS.inkFaint} />
      </g>
    ))}
  </svg>
);

const RemindersGlyph: React.FC = () => (
  <svg width="96" height="96" viewBox="0 0 96 96">
    <circle cx="48" cy="48" r="48" fill={COLORS.remindersOrange} />
    {[34, 48, 62].map((y) => (
      <g key={y}>
        <circle cx="31" cy={y} r="4.5" fill="white" />
        <line
          x1="42"
          y1={y}
          x2="68"
          y2={y}
          stroke="white"
          strokeWidth="5"
          strokeLinecap="round"
        />
      </g>
    ))}
  </svg>
);

const GoogleGlyph: React.FC = () => (
  <div
    style={{
      width: 96,
      height: 96,
      borderRadius: "50%",
      backgroundColor: COLORS.blue,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}
  >
    <svg width="56" height="56" viewBox="0 0 24 24">
      <path
        d="M5 12.5l4.5 4.5L19 7.5"
        fill="none"
        stroke="white"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  </div>
);
