# Local Tasks Bridge — promo video

**English** · [简体中文](#简体中文)

The product video for the website and README, made with
[Remotion](https://www.remotion.dev/) (React → MP4). Every scene is code, so
the video re-renders when the app or the wording changes, and new features are
added as new scenes. The storyboard and rules are in [brief.md](brief.md).

| Composition | Size | Language |
| --- | --- | --- |
| `Promo-EN` | 1920 × 1080, 30 fps | English |
| `Promo-ZH` | 1920 × 1080, 30 fps | Simplified Chinese |
| `Scenes/*` | each scene on its own | English (pass `--props='{"lang":"zh"}'` for Chinese) |

## Commands

Run these in `promo/` (Node.js 18 or later):

```bash
npm install          # once
npm run dev          # Remotion Studio: live preview at http://localhost:3000
npm run lint         # ESLint and TypeScript
npm run render       # out/promo-en.mp4 and out/promo-zh.mp4
npx remotion still Promo-EN out/frame.png --frame=380   # one frame, for checking
```

Working on the video with a coding agent? `npx remotion skills add` installs
Remotion's agent skills locally (they are not committed).

The first render downloads Chrome Headless Shell. Chinese text uses the
system font (PingFang SC on macOS), so render on a Mac for the intended look.

## Layout of `src/`

| Path | What it is |
| --- | --- |
| `Promo.tsx` | The full video: one `<TransitionSeries.Sequence>` per scene, 15-frame cross-fades |
| `Root.tsx` | Registers `Promo-EN`, `Promo-ZH` and every scene on its own |
| `scenes/` | One file per scene (= per feature) |
| `content/` | All on-screen text: `types.ts` (shape), `en.ts`, `zh.ts` |
| `components/` | Shared pieces: `SceneFrame`, `SceneTitle`, `TaskPanel`, `Bridge`, `TwoPanels`, `Brand` |
| `theme.ts` | Colours, Google Sans, type sizes, Material motion curves |
| `lib/progress.ts` | `ramp` / `flash` / `travel` helpers for frame-driven UI states |

## Adding a feature

1. **Text.** Add the scene's strings to `Content` in `src/content/types.ts`,
   then to `en.ts` and `zh.ts`. TypeScript fails until both languages have them.
2. **Scene.** Create `src/scenes/MyFeature.tsx`: export `MY_FEATURE_FRAMES`
   and a component that takes `{ lang }` and renders inside `<SceneFrame>`.
   Reuse `SceneTitle` and, for sync stories, `TwoPanels` + `TaskPanel` +
   `Bridge` so it matches the other scenes. Drive every animation from the
   frame (`useTimeline()` or `interpolate()`); CSS transitions don't render.
3. **Timeline.** In `src/Promo.tsx`, add a `<TransitionSeries.Sequence>` with
   a `{transition}` before it where the scene belongs, and add
   `MY_FEATURE_FRAMES` to the `PROMO_FRAMES` list so the length stays right.
4. **Registration.** In `src/Root.tsx`, add a `<Composition id="MyFeature">`
   inside the `Scenes` folder so it can be previewed on its own.
5. **Check.** `npm run lint`, look at stills of the new scene in both
   languages, then `npm run render`. Update the storyboard in `brief.md`.

Rules for every scene: one idea and one headline; text inside the safe area;
made-up demo data only; claims that match what the app really does; no
official Google or Apple logos.

## Licences

The video source is MIT-licensed like the rest of the repository. Remotion is
free for individuals and companies of up to three people; larger companies
need a [Remotion company licence](https://www.remotion.pro/license).
Google Sans is loaded from Google Fonts under the SIL Open Font License.

---

## 简体中文

官网和 README 用的产品视频，用 [Remotion](https://www.remotion.dev/)（React 生成 MP4）制作。每个场景都是代码：App 或文案变了，重新渲染就行；新功能就加一个新场景。分镜和规则见 [brief.md](brief.md)。

- `Promo-EN` / `Promo-ZH`：1920 × 1080、30 fps 的英文和中文完整版；`Scenes/*` 是单独的各个场景。
- 常用命令（在 `promo/` 下运行，需要 Node.js 18+）：`npm install`、`npm run dev`（实时预览）、`npm run lint`、`npm run render`（输出 `out/promo-en.mp4` 和 `out/promo-zh.mp4`）。
- 中文使用系统字体（macOS 上是苹方），请在 Mac 上渲染。
- 用 AI 编程助手改视频时，可以先运行 `npx remotion skills add` 在本地安装 Remotion 官方技能（不提交到仓库）。

**加一个新功能场景：**

1. 在 `src/content/types.ts` 的 `Content` 里加这个场景的文字字段，再在 `en.ts` 和 `zh.ts` 里各写一份；少写一种语言 TypeScript 就会报错。
2. 新建 `src/scenes/MyFeature.tsx`：导出 `MY_FEATURE_FRAMES` 和一个接收 `{ lang }`、包在 `<SceneFrame>` 里的组件；尽量复用 `SceneTitle`、`TwoPanels`、`TaskPanel`、`Bridge`，保持风格一致。所有动画都由帧驱动（`useTimeline()` 或 `interpolate()`），不要用 CSS 过渡。
3. 在 `src/Promo.tsx` 合适的位置加一个 `<TransitionSeries.Sequence>`（前面放 `{transition}`），并把 `MY_FEATURE_FRAMES` 加进 `PROMO_FRAMES` 列表。
4. 在 `src/Root.tsx` 的 `Scenes` 文件夹里注册 `<Composition id="MyFeature">`，方便单独预览。
5. 运行 `npm run lint`，导出新场景的中英文静帧检查，再 `npm run render`；同时更新 `brief.md` 的分镜表。

每个场景的规则：一个场景只讲一件事、一句标题；文字留在安全区内；只用虚构的演示数据；说法必须和 App 的实际行为一致；不使用 Google 或 Apple 的官方标志。
