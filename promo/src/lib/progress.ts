import { interpolate, useCurrentFrame } from "remotion";
import { CLAMP, EASE } from "../theme";

// Helpers for scenes that drive several UI states from one frame counter.
export const useTimeline = () => {
  const frame = useCurrentFrame();

  // 0 → 1 between two frames, with Material's emphasized easing.
  const ramp = (from: number, to: number, easing = EASE.emphasized) =>
    interpolate(frame, [from, to], [0, 1], { ...CLAMP, easing });

  // 0 → 1 → 0: a glow that flares at `from` and fades out by `to`.
  const flash = (from: number, to: number) =>
    interpolate(frame, [from, from + 6, to], [0, 1, 0], CLAMP);

  // Linear 0 → 1, for things that travel at constant speed.
  const travel = (from: number, to: number) =>
    interpolate(frame, [from, to], [0, 1], CLAMP);

  return { frame, ramp, flash, travel };
};
