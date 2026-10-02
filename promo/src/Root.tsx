import type React from "react";
import { Composition, Folder } from "remotion";
import { Promo, PROMO_FRAMES } from "./Promo";
import { CompleteAndEdit, COMPLETE_AND_EDIT_FRAMES } from "./scenes/CompleteAndEdit";
import { GoogleToReminders, GOOGLE_TO_REMINDERS_FRAMES } from "./scenes/GoogleToReminders";
import { Intro, INTRO_FRAMES } from "./scenes/Intro";
import { MenuBar, MENU_BAR_FRAMES } from "./scenes/MenuBar";
import { Outro, OUTRO_FRAMES } from "./scenes/Outro";
import { Privacy, PRIVACY_FRAMES } from "./scenes/Privacy";
import { RemindersToGoogle, REMINDERS_TO_GOOGLE_FRAMES } from "./scenes/RemindersToGoogle";
import { SafetyReview, SAFETY_REVIEW_FRAMES } from "./scenes/SafetyReview";
import { TwoPlaces, TWO_PLACES_FRAMES } from "./scenes/TwoPlaces";
import { FPS, HEIGHT, WIDTH } from "./theme";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Promo-EN"
        component={Promo}
        durationInFrames={PROMO_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={{ lang: "en" as const }}
      />
      <Composition
        id="Promo-ZH"
        component={Promo}
        durationInFrames={PROMO_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={{ lang: "zh" as const }}
      />
      {/* Each scene on its own, in storyboard order, for previewing one feature at a time. */}
      <Folder name="Scenes">
        <Composition
          id="Intro"
          component={Intro}
          durationInFrames={INTRO_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{ lang: "en" as const }}
        />
        <Composition
          id="TwoPlaces"
          component={TwoPlaces}
          durationInFrames={TWO_PLACES_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{ lang: "en" as const }}
        />
        <Composition
          id="GoogleToReminders"
          component={GoogleToReminders}
          durationInFrames={GOOGLE_TO_REMINDERS_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{ lang: "en" as const }}
        />
        <Composition
          id="RemindersToGoogle"
          component={RemindersToGoogle}
          durationInFrames={REMINDERS_TO_GOOGLE_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{ lang: "en" as const }}
        />
        <Composition
          id="CompleteAndEdit"
          component={CompleteAndEdit}
          durationInFrames={COMPLETE_AND_EDIT_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{ lang: "en" as const }}
        />
        <Composition
          id="SafetyReview"
          component={SafetyReview}
          durationInFrames={SAFETY_REVIEW_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{ lang: "en" as const }}
        />
        <Composition
          id="Privacy"
          component={Privacy}
          durationInFrames={PRIVACY_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{ lang: "en" as const }}
        />
        <Composition
          id="MenuBar"
          component={MenuBar}
          durationInFrames={MENU_BAR_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{ lang: "en" as const }}
        />
        <Composition
          id="Outro"
          component={Outro}
          durationInFrames={OUTRO_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
          defaultProps={{ lang: "en" as const }}
        />
      </Folder>
    </>
  );
};
