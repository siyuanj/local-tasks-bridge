import type React from "react";
import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { CLAMP, EASE, GOOGLE_DOTS, SHADOW } from "../theme";

// The app icon, popping in at `at`.
export const AppIcon: React.FC<{ readonly size: number; readonly at?: number }> = ({
  size,
  at = 0,
}) => {
  const frame = useCurrentFrame();

  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.225,
        overflow: "hidden",
        boxShadow: SHADOW,
        opacity: interpolate(frame, [at, at + 8], [0, 1], CLAMP),
        scale: interpolate(frame, [at, at + 20], [0.5, 1], {
          ...CLAMP,
          easing: EASE.emphasized,
          output: "perceptual-scale",
        }),
      }}
    >
      <Img src={staticFile("icon.png")} style={{ width: size, height: size }} />
    </div>
  );
};

// Google's four colour dots, popping in one after another from `at`.
export const ColorDots: React.FC<{ readonly at: number; readonly size?: number }> = ({
  at,
  size = 26,
}) => {
  const frame = useCurrentFrame();

  return (
    <div style={{ display: "flex", gap: size * 0.9, justifyContent: "center" }}>
      {GOOGLE_DOTS.map((color, i) => (
        <div
          key={color}
          style={{
            width: size,
            height: size,
            borderRadius: "50%",
            backgroundColor: color,
            scale: interpolate(frame, [at + i * 4, at + i * 4 + 14], [0, 1], {
              ...CLAMP,
              easing: EASE.emphasized,
              output: "perceptual-scale",
            }),
          }}
        />
      ))}
    </div>
  );
};
