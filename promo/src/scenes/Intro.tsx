import type React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { AppIcon, ColorDots } from "../components/Brand";
import { SceneFrame } from "../components/SceneFrame";
import { getContent, type LangProps } from "../content";
import { CLAMP, COLORS, EASE, TYPE } from "../theme";

export const INTRO_FRAMES = 120;

export const Intro: React.FC<LangProps> = ({ lang }) => {
  const frame = useCurrentFrame();
  const t = getContent(lang).intro;

  return (
    <SceneFrame>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 40,
        }}
      >
        <AppIcon size={220} at={0} />
        <div
          style={{
            fontSize: TYPE.hero,
            fontWeight: 700,
            letterSpacing: "-0.03em",
            opacity: interpolate(frame, [12, 26], [0, 1], CLAMP),
            translate: interpolate(frame, [12, 32], ["0px 40px", "0px 0px"], {
              ...CLAMP,
              easing: EASE.decelerate,
            }),
          }}
        >
          {t.title}
        </div>
        <div
          style={{
            marginTop: -16,
            fontSize: TYPE.note + 4,
            fontWeight: 500,
            color: COLORS.inkSoft,
            opacity: interpolate(frame, [24, 38], [0, 1], CLAMP),
            translate: interpolate(frame, [24, 44], ["0px 30px", "0px 0px"], {
              ...CLAMP,
              easing: EASE.decelerate,
            }),
          }}
        >
          {t.tagline}
        </div>
        <ColorDots at={38} />
      </div>
    </SceneFrame>
  );
};
