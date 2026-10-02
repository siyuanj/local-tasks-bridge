import type React from "react";

// Google Tasks on the left, the bridge in the middle, Reminders on the right,
// below the headline. Shared by every sync scene so they line up across cuts.
export const PANEL_WIDTH = 640;
export const BRIDGE_WIDTH = 240;

export const TwoPanels: React.FC<{
  readonly left: React.ReactNode;
  readonly bridge: React.ReactNode;
  readonly right: React.ReactNode;
  readonly top?: number;
}> = ({ left, bridge, right, top = 330 }) => (
  <div
    style={{
      position: "absolute",
      top,
      left: 0,
      right: 0,
      display: "flex",
      justifyContent: "center",
      alignItems: "flex-start",
    }}
  >
    {left}
    <div style={{ paddingTop: 150 }}>{bridge}</div>
    {right}
  </div>
);
