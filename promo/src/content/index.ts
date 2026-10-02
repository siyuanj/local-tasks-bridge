import { en } from "./en";
import type { Content, Lang } from "./types";
import { zh } from "./zh";

export type { Content, DemoTask, Lang } from "./types";

const CONTENT: Record<Lang, Content> = { en, zh };

export const getContent = (lang: Lang): Content => CONTENT[lang];

// Props shared by every scene and by the full video.
export type LangProps = {
  readonly lang: Lang;
};
