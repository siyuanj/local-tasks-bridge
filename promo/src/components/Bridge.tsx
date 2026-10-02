import type React from "react";
import { Img, interpolate, staticFile } from "remotion";
import { CLAMP, COLORS, EASE, GOOGLE_DOTS, SHADOW } from "../theme";

type Props = {
  readonly width: number;
  // Position of a travelling sync pulse, 0–1 along the bridge (invisible at
  // either end), or null for none.
  readonly pulse?: number | null;
  // "ltr": Google Tasks → Reminders; "rtl": Reminders → Google Tasks.
  readonly direction?: "ltr" | "rtl";
  // 1 = connected; 0 = broken in the middle (no app yet).
  readonly connected?: number;
  // 0–1: a "held" badge replaces the pulse (safety review).
  readonly held?: number;
  readonly style?: React.CSSProperties;
};

// The line between the two panels with the app icon in the middle.
export const Bridge: React.FC<Props> = ({
  width,
  pulse = null,
  direction = "ltr",
  connected = 1,
  held = 0,
  style,
}) => {
  const position = pulse === null ? null : direction === "ltr" ? pulse : 1 - pulse;
  const gap = (1 - connected) * 70;

  return (
    <div style={{ position: "relative", width, height: 120, ...style }}>
      {[0, 1].map((side) => (
        <div
          key={side}
          style={{
            position: "absolute",
            top: 58,
            height: 4,
            borderRadius: 2,
            left: side === 0 ? 0 : width / 2 + gap / 2,
            width: width / 2 - gap / 2,
            backgroundImage: `linear-gradient(90deg, ${COLORS.outline} 50%, transparent 50%)`,
            backgroundSize: "16px 4px",
          }}
        />
      ))}
      {position !== null ? (
        <div
          style={{
            position: "absolute",
            top: 60 - 14,
            left: position * width - 14,
            width: 28,
            height: 28,
            borderRadius: "50%",
            backgroundColor: GOOGLE_DOTS[Math.floor(position * 3.999)],
            boxShadow: `0 0 0 10px rgba(66, 133, 244, 0.12)`,
            opacity: interpolate(pulse ?? 0, [0, 0.08, 0.92, 1], [0, 1, 1, 0], CLAMP),
          }}
        />
      ) : null}
      <div
        style={{
          position: "absolute",
          left: width / 2 - 46,
          top: 14,
          width: 92,
          height: 92,
          borderRadius: 24,
          boxShadow: SHADOW,
          overflow: "hidden",
          opacity: connected,
          scale: String(interpolate(connected, [0, 1], [0.6, 1], { ...CLAMP, easing: EASE.emphasized })),
        }}
      >
        <Img src={staticFile("icon.png")} style={{ width: 92, height: 92 }} />
      </div>
      {held > 0 ? (
        <div
          style={{
            position: "absolute",
            left: width / 2 - 34,
            top: -54,
            width: 68,
            height: 68,
            borderRadius: "50%",
            backgroundColor: COLORS.yellow,
            boxShadow: SHADOW,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            opacity: held,
            scale: String(interpolate(held, [0, 1], [0.4, 1], { ...CLAMP, easing: EASE.emphasized })),
          }}
        >
          <div style={{ display: "flex", gap: 9 }}>
            <div style={{ width: 9, height: 28, borderRadius: 3, backgroundColor: COLORS.ink }} />
            <div style={{ width: 9, height: 28, borderRadius: 3, backgroundColor: COLORS.ink }} />
          </div>
        </div>
      ) : null}
    </div>
  );
};
