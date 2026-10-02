import type React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { CLAMP, COLORS, EASE, TYPE } from "../theme";

type Props = {
  readonly title: string;
  readonly note?: string;
  // Frame at which the headline leaves the centre for the top of the frame.
  // Omit it to start at the top, when the UI is already on screen.
  readonly moveAt?: number;
  // Frame at which the supporting line fades in under the headline.
  readonly noteAt?: number;
};

// The headline waits until the previous scene has mostly faded out
// (cross-fades are 15 frames), so two headlines never overlap.
const ENTER_AT = 13;

// A scene's headline: it lands in the centre, then glides to the top to make
// room for the UI. The note appears under it once the action has happened.
export const SceneTitle: React.FC<Props> = ({
  title,
  note,
  moveAt = -100,
  noteAt,
}) => {
  const frame = useCurrentFrame();

  return (
    <div
      style={{
        position: "absolute",
        left: 140,
        right: 140,
        top: interpolate(frame, [moveAt, moveAt + 22], [420, 92], {
          ...CLAMP,
          easing: EASE.emphasized,
        }),
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontSize: TYPE.headline,
          fontWeight: 700,
          letterSpacing: "-0.02em",
          lineHeight: 1.1,
          transformOrigin: "50% 0%",
          scale: interpolate(frame, [moveAt, moveAt + 22], [1.12, 0.86], {
            ...CLAMP,
            easing: EASE.emphasized,
          }),
          opacity: interpolate(frame, [ENTER_AT, ENTER_AT + 12], [0, 1], CLAMP),
          translate: interpolate(frame, [ENTER_AT, ENTER_AT + 16], ["0px 30px", "0px 0px"], {
            ...CLAMP,
            easing: EASE.decelerate,
          }),
        }}
      >
        {title}
      </div>
      {note && noteAt !== undefined ? (
        <div
          style={{
            marginTop: 4,
            fontSize: TYPE.note,
            fontWeight: 500,
            color: COLORS.inkSoft,
            opacity: interpolate(frame, [noteAt, noteAt + 14], [0, 1], CLAMP),
            translate: interpolate(frame, [noteAt, noteAt + 18], ["0px 18px", "0px 0px"], {
              ...CLAMP,
              easing: EASE.decelerate,
            }),
          }}
        >
          {note}
        </div>
      ) : null}
    </div>
  );
};
