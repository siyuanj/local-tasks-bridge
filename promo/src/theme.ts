import { loadFont } from "@remotion/google-fonts/GoogleSans";
import { Easing } from "remotion";

const { fontFamily: googleSans } = loadFont("normal", {
  weights: ["400", "500", "700"],
  subsets: ["latin", "latin-ext", "symbols"],
});

// Chinese falls back to the system font (PingFang SC on macOS).
export const FONT = `${googleSans}, "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", sans-serif`;

export const COLORS = {
  blue: "#4285F4",
  red: "#EA4335",
  yellow: "#FBBC04",
  green: "#34A853",
  ink: "#1F1F1F",
  inkSoft: "#5E6368",
  inkFaint: "#9AA0A6",
  canvas: "#FFFFFF",
  surface: "#F0F4F9",
  outline: "#E1E3E6",
  remindersOrange: "#FF9500",
} as const;

export const GOOGLE_DOTS = [COLORS.blue, COLORS.red, COLORS.yellow, COLORS.green] as const;

// Material 3 motion curves.
export const EASE = {
  emphasized: Easing.bezier(0.2, 0, 0, 1),
  decelerate: Easing.bezier(0.05, 0.7, 0.1, 1),
  accelerate: Easing.bezier(0.3, 0, 0.8, 0.15),
} as const;

export const CLAMP = {
  extrapolateLeft: "clamp",
  extrapolateRight: "clamp",
} as const;

export const TYPE = {
  hero: 132,
  headline: 96,
  note: 50,
  ui: 38,
  uiSmall: 28,
} as const;

export const SHADOW =
  "0 1px 3px rgba(60, 64, 67, 0.12), 0 12px 40px rgba(60, 64, 67, 0.14)";

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
