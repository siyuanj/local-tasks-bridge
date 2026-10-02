import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import type React from "react";
import { useVideoConfig } from "remotion";
import type { LangProps } from "./content";
import { CompleteAndEdit, COMPLETE_AND_EDIT_FRAMES } from "./scenes/CompleteAndEdit";
import { GoogleToReminders, GOOGLE_TO_REMINDERS_FRAMES } from "./scenes/GoogleToReminders";
import { Intro, INTRO_FRAMES } from "./scenes/Intro";
import { MenuBar, MENU_BAR_FRAMES } from "./scenes/MenuBar";
import { Outro, OUTRO_FRAMES } from "./scenes/Outro";
import { Privacy, PRIVACY_FRAMES } from "./scenes/Privacy";
import { RemindersToGoogle, REMINDERS_TO_GOOGLE_FRAMES } from "./scenes/RemindersToGoogle";
import { SafetyReview, SAFETY_REVIEW_FRAMES } from "./scenes/SafetyReview";
import { TwoPlaces, TWO_PLACES_FRAMES } from "./scenes/TwoPlaces";

// The full video. Each scene is one <TransitionSeries.Sequence>; scenes are
// separated by a 15-frame cross-fade. To add a feature: write the scene in
// src/scenes/, add it below and register it in Root.tsx (see README.md).
export const TRANSITION_FRAMES = 15;

const transition = (
  <TransitionSeries.Transition
    presentation={fade()}
    timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
  />
);

export const Promo: React.FC<LangProps> = ({ lang }) => {
  const { fps } = useVideoConfig();

  return (
    <TransitionSeries>
      <TransitionSeries.Sequence name="Intro" durationInFrames={INTRO_FRAMES} premountFor={fps}>
        <Intro lang={lang} />
      </TransitionSeries.Sequence>
      {transition}
      <TransitionSeries.Sequence name="Two places" durationInFrames={TWO_PLACES_FRAMES} premountFor={fps}>
        <TwoPlaces lang={lang} />
      </TransitionSeries.Sequence>
      {transition}
      <TransitionSeries.Sequence name="Google Tasks to Reminders" durationInFrames={GOOGLE_TO_REMINDERS_FRAMES} premountFor={fps}>
        <GoogleToReminders lang={lang} />
      </TransitionSeries.Sequence>
      {transition}
      <TransitionSeries.Sequence name="Reminders to Google Tasks" durationInFrames={REMINDERS_TO_GOOGLE_FRAMES} premountFor={fps}>
        <RemindersToGoogle lang={lang} />
      </TransitionSeries.Sequence>
      {transition}
      <TransitionSeries.Sequence name="Complete and edit" durationInFrames={COMPLETE_AND_EDIT_FRAMES} premountFor={fps}>
        <CompleteAndEdit lang={lang} />
      </TransitionSeries.Sequence>
      {transition}
      <TransitionSeries.Sequence name="Safety review" durationInFrames={SAFETY_REVIEW_FRAMES} premountFor={fps}>
        <SafetyReview lang={lang} />
      </TransitionSeries.Sequence>
      {transition}
      <TransitionSeries.Sequence name="Privacy" durationInFrames={PRIVACY_FRAMES} premountFor={fps}>
        <Privacy lang={lang} />
      </TransitionSeries.Sequence>
      {transition}
      <TransitionSeries.Sequence name="Menu bar" durationInFrames={MENU_BAR_FRAMES} premountFor={fps}>
        <MenuBar lang={lang} />
      </TransitionSeries.Sequence>
      {transition}
      <TransitionSeries.Sequence name="Outro" durationInFrames={OUTRO_FRAMES} premountFor={fps}>
        <Outro lang={lang} />
      </TransitionSeries.Sequence>
    </TransitionSeries>
  );
};

// Sum of the scenes minus the overlap of each cross-fade.
export const promoDuration = (scenes: readonly number[]) =>
  scenes.reduce((total, frames) => total + frames, 0) -
  (scenes.length - 1) * TRANSITION_FRAMES;

export const PROMO_FRAMES = promoDuration([
  INTRO_FRAMES,
  TWO_PLACES_FRAMES,
  GOOGLE_TO_REMINDERS_FRAMES,
  REMINDERS_TO_GOOGLE_FRAMES,
  COMPLETE_AND_EDIT_FRAMES,
  SAFETY_REVIEW_FRAMES,
  PRIVACY_FRAMES,
  MENU_BAR_FRAMES,
  OUTRO_FRAMES,
]);
