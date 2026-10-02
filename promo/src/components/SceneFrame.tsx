import type React from "react";
import { AbsoluteFill } from "remotion";
import { COLORS, FONT } from "../theme";

// The white canvas every scene sits on, with faint Google-colour glows.
export const SceneFrame: React.FC<{ readonly children: React.ReactNode }> = ({
  children,
}) => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.canvas,
        fontFamily: FONT,
        color: COLORS.ink,
        overflow: "hidden",
      }}
    >
      <Glow color={COLORS.blue} left={-260} top={-320} />
      <Glow color={COLORS.yellow} left={1500} top={-260} />
      <Glow color={COLORS.green} left={-200} top={760} />
      <Glow color={COLORS.red} left={1560} top={820} />
      {children}
    </AbsoluteFill>
  );
};

const Glow: React.FC<{
  readonly color: string;
  readonly left: number;
  readonly top: number;
}> = ({ color, left, top }) => (
  <div
    style={{
      position: "absolute",
      left,
      top,
      width: 640,
      height: 640,
      borderRadius: "50%",
      backgroundColor: color,
      opacity: 0.07,
      filter: "blur(120px)",
    }}
  />
);
