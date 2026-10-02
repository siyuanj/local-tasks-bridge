import type React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { AppIcon, ColorDots } from "../components/Brand";
import { SceneFrame } from "../components/SceneFrame";
import { getContent, type LangProps } from "../content";
import { CLAMP, COLORS, EASE, TYPE } from "../theme";

export const OUTRO_FRAMES = 150;

export const Outro: React.FC<LangProps> = ({ lang }) => {
  const frame = useCurrentFrame();
  const t = getContent(lang).outro;

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
        <AppIcon size={180} at={0} />
        <div
          style={{
            fontSize: TYPE.hero,
            fontWeight: 700,
            letterSpacing: "-0.03em",
            opacity: interpolate(frame, [10, 24], [0, 1], CLAMP),
            translate: interpolate(frame, [10, 30], ["0px 40px", "0px 0px"], {
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
            fontSize: TYPE.note,
            fontWeight: 500,
            color: COLORS.inkSoft,
            opacity: interpolate(frame, [22, 36], [0, 1], CLAMP),
            translate: interpolate(frame, [22, 42], ["0px 30px", "0px 0px"], {
              ...CLAMP,
              easing: EASE.decelerate,
            }),
          }}
        >
          {t.tagline}
        </div>
        <div
          style={{
            padding: "12px 40px",
            borderRadius: 999,
            border: `2px solid ${COLORS.outline}`,
            fontSize: 44,
            fontWeight: 500,
            color: COLORS.blue,
            whiteSpace: "nowrap",
            opacity: interpolate(frame, [34, 48], [0, 1], CLAMP),
            translate: interpolate(frame, [34, 54], ["0px 30px", "0px 0px"], {
              ...CLAMP,
              easing: EASE.decelerate,
            }),
          }}
        >
          {t.url}
        </div>
        <ColorDots at={46} />
      </div>
    </SceneFrame>
  );
};
