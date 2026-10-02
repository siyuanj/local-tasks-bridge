# Promo video brief

## Goal

A short product video for the website and README that shows what Local Tasks
Bridge does, in the style of Google's product videos: white space, Google's
four colours as accents, Google Sans, big confident headlines, simple UI
mock-ups and calm Material motion. No voice-over (captions carry the story);
music and sound effects come in a later pass.

- Audience: Mac users who also use Google Tasks (often through Gemini or an
  Android phone) and want their tasks in Apple Reminders.
- Formats: 1920 × 1080, 30 fps, English (`Promo-EN`) and Chinese (`Promo-ZH`).
  A vertical 1080 × 1920 cut can reuse the same scenes later.
- Length: about 50 seconds.

## Rules

- One idea per scene, one headline per scene. The viewer should notice one thing first.
- Text inside the safe area (at least 140 px from the sides, 100 px from top
  and bottom at 1920 × 1080). Headlines ≥ 84 px, supporting text ≥ 48 px.
- Mock-ups use made-up demo tasks only. No real accounts, names or data.
- Google Tasks and Reminders are named, never imitated with their official
  logos; nothing suggests Google or Apple made or endorses the app.
- Claims must match the app: two-way sync, Reminders changes sync right away,
  large deletions are held for review (more than 25 items or 25 %), no server
  in between, sign-in stays on the Mac.

## Storyboard

| # | Scene (file) | Seconds | What happens | Headline (EN) |
|---|---|---|---|---|
| 1 | `Intro` | 4 | App icon pops in, name and tagline, Google colour dots | Local Tasks Bridge |
| 2 | `TwoPlaces` | 5 | Google Tasks and Reminders panels drift in, a broken line between them | Your tasks live in two places. |
| 3 | `GoogleToReminders` | 7 | A task is typed in Google Tasks, travels across the bridge, lands in Reminders | Add a task in Google Tasks… |
| 4 | `RemindersToGoogle` | 6 | The reverse: added in Reminders (or with Siri), appears in Google Tasks | …or in Reminders, even with Siri. |
| 5 | `CompleteAndEdit` | 7 | A completion and a due-date change sync in both directions | Check it off. Change the date. |
| 6 | `SafetyReview` | 8 | Many reminders vanish at once; the bridge holds them and asks for review | Big deletions wait for your OK. |
| 7 | `Privacy` | 6 | Mac in the middle, direct lines to Reminders and Google, a crossed-out server | No servers in between. |
| 8 | `MenuBar` | 6 | The menu bar icon opens the real menu; Sync Now runs | Lives in your menu bar. |
| 9 | `Outro` | 5 | Icon, name, "free and open source", website address | Local Tasks Bridge |

Transitions: 15-frame cross-fades between scenes.

## Acceptance

- `npm run lint` passes (ESLint and TypeScript).
- Stills of each scene show no clipped or overlapping text in either language.
- `npx remotion render Promo-EN` and `Promo-ZH` exit with code 0; ffprobe
  reports 1920 × 1080, 30 fps and the expected duration.
