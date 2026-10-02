import type React from "react";
import { COLORS, SHADOW, TYPE } from "../theme";

export type PanelKind = "google" | "reminders";

// The animated state of one row. Every value is 0–1 and computed by the scene
// from the current frame, so panels stay simple, stateless views.
export type RowState = {
  readonly id: string;
  readonly title: string;
  readonly due?: string;
  readonly enter?: number; // 0 = collapsed, 1 = fully shown
  readonly typed?: number; // share of the title typed so far
  readonly done?: number; // completion progress
  readonly highlight?: number; // "just synced" glow
  readonly dueSwap?: { readonly to: string; readonly progress: number };
};

type Props = {
  readonly kind: PanelKind;
  readonly heading: string;
  readonly listName: string;
  readonly rows: readonly RowState[];
  readonly width?: number;
  readonly style?: React.CSSProperties;
};

const ROW_HEIGHT = 92;

// A neutral mock-up of a task list: Google Tasks (blue, Material) or
// Reminders (orange, macOS). Not the real apps' logos or UI.
export const TaskPanel: React.FC<Props> = ({
  kind,
  heading,
  listName,
  rows,
  width = 640,
  style,
}) => {
  const accent = kind === "google" ? COLORS.blue : COLORS.remindersOrange;

  return (
    <div
      style={{
        width,
        backgroundColor: COLORS.canvas,
        borderRadius: 32,
        boxShadow: SHADOW,
        padding: "30px 36px 26px",
        boxSizing: "border-box",
        ...style,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14, height: 44 }}>
        {kind === "google" ? <GoogleBadge /> : <WindowDots />}
        <div
          style={{
            fontSize: TYPE.uiSmall,
            fontWeight: 500,
            color: COLORS.inkSoft,
            marginLeft: kind === "google" ? 0 : 10,
          }}
        >
          {heading}
        </div>
      </div>
      <div
        style={{
          fontSize: 46,
          fontWeight: 700,
          color: kind === "google" ? COLORS.ink : accent,
          margin: "16px 0 10px",
          letterSpacing: "-0.01em",
        }}
      >
        {listName}
      </div>
      {rows.map((row) => (
        <TaskRow key={row.id} row={row} accent={accent} kind={kind} />
      ))}
    </div>
  );
};

const TaskRow: React.FC<{
  readonly row: RowState;
  readonly accent: string;
  readonly kind: PanelKind;
}> = ({ row, accent, kind }) => {
  const enter = row.enter ?? 1;
  const done = row.done ?? 0;
  const highlight = row.highlight ?? 0;
  const typed = row.typed ?? 1;
  const shownTitle = Array.from(row.title)
    .slice(0, Math.round(Array.from(row.title).length * typed))
    .join("");

  return (
    <div
      style={{
        height: ROW_HEIGHT * enter,
        opacity: enter,
        overflow: "hidden",
        margin: "0 -16px",
        padding: "0 16px",
        borderRadius: 18,
        backgroundColor: `rgba(${kind === "google" ? "66, 133, 244" : "255, 149, 0"}, ${0.12 * highlight})`,
      }}
    >
      <div
        style={{
          height: ROW_HEIGHT,
          display: "flex",
          alignItems: "center",
          gap: 22,
          translate: `0px ${(1 - enter) * 24}px`,
        }}
      >
        <Check accent={accent} done={done} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: TYPE.ui,
              fontWeight: 500,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              color: done > 0.5 ? COLORS.inkFaint : COLORS.ink,
              textDecoration: done > 0.5 ? "line-through" : "none",
            }}
          >
            {shownTitle}
            {typed < 1 ? <Caret color={accent} /> : null}
          </div>
        </div>
        {row.due ? <Due kind={kind} due={row.due} swap={row.dueSwap} /> : null}
      </div>
    </div>
  );
};

const Check: React.FC<{ readonly accent: string; readonly done: number }> = ({
  accent,
  done,
}) => (
  <div
    style={{
      width: 38,
      height: 38,
      flexShrink: 0,
      borderRadius: "50%",
      boxSizing: "border-box",
      border: `3px solid ${done > 0 ? accent : COLORS.inkFaint}`,
      backgroundColor: done > 0 ? accent : "transparent",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      scale: String(1 + Math.sin(Math.PI * Math.min(done, 1)) * 0.18),
    }}
  >
    <svg width="22" height="22" viewBox="0 0 24 24" style={{ opacity: done }}>
      <path
        d="M5 12.5l4.5 4.5L19 7.5"
        fill="none"
        stroke="white"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  </div>
);

const Due: React.FC<{
  readonly kind: PanelKind;
  readonly due: string;
  readonly swap?: RowState["dueSwap"];
}> = ({ kind, due, swap }) => {
  const progress = swap?.progress ?? 0;
  const text = swap && progress > 0.5 ? swap.to : due;
  const pop = 1 + Math.sin(Math.PI * progress) * 0.15;
  const google = kind === "google";

  return (
    <div
      style={{
        flexShrink: 0,
        fontSize: TYPE.uiSmall,
        fontWeight: 500,
        padding: google ? "6px 16px" : "6px 4px",
        borderRadius: 999,
        border: google ? `2px solid ${COLORS.outline}` : "none",
        color: google ? COLORS.blue : COLORS.inkSoft,
        scale: String(pop),
      }}
    >
      {text}
    </div>
  );
};

const Caret: React.FC<{ readonly color: string }> = ({ color }) => (
  <span
    style={{
      display: "inline-block",
      width: 3,
      height: "1em",
      marginLeft: 3,
      verticalAlign: "-0.12em",
      backgroundColor: color,
    }}
  />
);

const GoogleBadge: React.FC = () => (
  <div
    style={{
      width: 40,
      height: 40,
      borderRadius: "50%",
      backgroundColor: COLORS.blue,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}
  >
    <svg width="24" height="24" viewBox="0 0 24 24">
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

const WindowDots: React.FC = () => (
  <div style={{ display: "flex", gap: 10 }}>
    {["#FF5F57", "#FEBC2E", "#28C840"].map((color) => (
      <div
        key={color}
        style={{ width: 18, height: 18, borderRadius: "50%", backgroundColor: color }}
      />
    ))}
  </div>
);
