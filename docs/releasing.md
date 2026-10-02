# Releasing (maintainers)

**English** · [简体中文](releasing.zh-CN.md)

This page is for the maintainer. It covers version numbers, cutting a release,
the GitHub secrets, Google OAuth verification of the shared client, the Tasks
API quota, making the repository public and a future Homebrew tap.

## Versions

Local Tasks Bridge follows [Semantic Versioning](https://semver.org/):

- **MAJOR** for incompatible changes to what users or scripts rely on: the
  layout or meaning of `config.json` and `state.json`, the JSON output and exit
  codes of `ltb` ([contract](app-engine-contract.md)), file locations, or
  dropping a supported macOS version.
- **MINOR** for new features that keep existing installations working.
- **PATCH** for fixes.

The version lives in three places that must agree:

| Place | Example |
| --- | --- |
| `VERSION` (repository root) | `1.0.0` |
| `__version__` in `engine/local_tasks_bridge.py` | `__version__ = "1.0.0"` |
| `CHANGELOG.md` heading | `## [1.0.0] - 2026-10-01` |

`scripts/build-app.sh` writes the version into the app's `Info.plist`, and
`scripts/package-release.sh` refuses to package when `VERSION` and
`__version__` differ, or when the built app reports another version.

## Cutting a release

1. **Start from a green `main`.** CI runs the unit and end-to-end tests on
   Python 3.9, 3.12 and 3.13, lints the scripts and workflows with pinned
   tools (a missing tool fails lint there, `LINT_REQUIRE=1`), and builds and
   smoke-tests the app on macOS.
2. **Prepare the release on a branch** (`release/vX.Y.Z`):
   - set `VERSION` and `__version__` in `engine/local_tasks_bridge.py`;
   - move the entries under `## [Unreleased]` in `CHANGELOG.md` into a new
     `## [X.Y.Z] - YYYY-MM-DD` section and update the comparison links at the
     bottom — this section becomes the release notes;
   - update the docs if behavior changed (both languages);
   - run `make lint test`.
3. **Merge** the pull request into `main`.
4. **Optionally build locally** to catch packaging problems early: `make
   package` writes the two zips, `SHA256SUMS` and `release-manifest.json` (what
   was built, from which commit and how) into `dist/`.
5. **Check the source, then tag and push.** The release source gate fails
   unless the checkout is a clean `main` whose `HEAD` equals `origin/main`, the
   live `main` on GitHub and the commit you reviewed:

   ```bash
   git switch main && git pull --ff-only
   DEPLOY_EXPECTED_COMMIT="$(git rev-parse HEAD)" scripts/check-release-source.sh
   git tag -a vX.Y.Z -m "Local Tasks Bridge X.Y.Z"
   git push origin vX.Y.Z
   ```

The pushed tag starts `.github/workflows/release.yml`; for an existing tag the
workflow can also be started by hand (Actions → Release → *Run workflow*). It:

1. accepts only a strict `vX.Y.Z` tag on a commit that is on `main`, and checks
   that `VERSION` and the engine's `__version__` both equal `X.Y.Z`;
2. extracts the release notes from the `## [X.Y.Z]` section of `CHANGELOG.md`
   with `.github/scripts/release-notes.sh` — a missing or empty section stops
   the release;
3. runs the tests with the macOS system Python and with the embedded Python,
   plus the installer and release-gate self-tests;
4. imports the Developer ID certificate into a temporary keychain if all three
   `MACOS_*` secrets exist (otherwise the builds are ad-hoc signed), and
   notarizes if the three Apple secrets exist;
5. runs `scripts/package-release.sh --arch all` with the shared OAuth client
   from `LTB_OAUTH_CLIENT_JSON`: both architectures with an embedded Python,
   `SHA256SUMS` and `release-manifest.json`. Without that secret the builds have
   no shared client and the job summary shows a warning; with the repository
   variable `LTB_REQUIRE_SHARED_CLIENT` set to `true`, the release fails
   instead;
6. installs Rosetta and smoke-tests both zips with `install.sh` in a
   temporary home; on a tag build, a smoke test that can't run fails the
   release;
7. refuses to overwrite an existing release, uploads the two zips,
   `SHA256SUMS` and `release-manifest.json` to a draft release, and then
   publishes it.

Then **test the published release** before announcing it, on a separate macOS
user account if possible: the one-line installer (it installs the release
GitHub marks as *Latest*), a browser download with the Gatekeeper steps,
`shasum -a 256` against `SHA256SUMS`, the setup assistant with each sign-in
method and a test list, an upgrade from the previous release (settings and sync
map kept), **Check for Updates…**, and uninstalling.

If something is wrong after publishing, delete the GitHub release and the tag,
fix it on `main`, and release a new PATCH version. Never replace the assets of a
published version: users and `SHA256SUMS` rely on them being immutable.

## GitHub secrets

Settings → Secrets and variables → Actions:

| Secret | Purpose |
| --- | --- |
| `LTB_OAUTH_CLIENT_JSON` | The complete JSON file (`{"installed": {…}}`) of the maintainer's **Desktop app** OAuth client “Local Tasks Bridge”. The workflow places it in the app as `Contents/Resources/oauth_client.json`. |
| `MACOS_CERTIFICATE_P12_BASE64` | Future: the Developer ID Application certificate and private key, exported as `.p12` and base64-encoded |
| `MACOS_CERTIFICATE_PASSWORD` | Future: the password of that `.p12` |
| `MACOS_SIGN_IDENTITY` | Future: the signing identity, for example `Developer ID Application: Siyuan Jiang (TEAMID1234)` |
| `APPLE_ID` | Future: the Apple ID used for notarization |
| `APPLE_TEAM_ID` | Future: the Apple Developer team ID |
| `APPLE_APP_PASSWORD` | Future: an app-specific password for that Apple ID (appleid.apple.com → Sign-In and Security → App-Specific Passwords) |

Repository variable (Settings → Secrets and variables → Actions → Variables):
`LTB_REQUIRE_SHARED_CLIENT=true` makes a release without
`LTB_OAUTH_CLIENT_JSON` fail instead of only warning.

`scripts/package-release.sh` reads the client from `LTB_OAUTH_CLIENT_JSON` (or a
file path in `LTB_OAUTH_CLIENT_FILE`), signs with `LTB_SIGN_IDENTITY` (default
`-`, ad-hoc), and notarizes and staples with `LTB_NOTARIZE=1` plus `APPLE_ID`,
`APPLE_TEAM_ID` and `APPLE_APP_PASSWORD`. It never prints these values.

**Never commit the OAuth client JSON.** `.gitignore` excludes `client_secret*.json`
and `credentials.json`, but check `git status` anyway. Google treats the client
secret of a desktop app as not truly confidential — it ships inside every copy
of the app — but keeping it out of the repository limits abuse of the shared
quota and makes rotation simple: add a new secret to the client in the Google
Cloud console, update the GitHub secret, release, and delete the old secret
once users have updated.

**Developer ID (later).** Signing with a Developer ID (Apple Developer Program)
plus notarization removes the Gatekeeper prompt, keeps the Reminders permission
across updates, and makes Keychain access rules stable — the prerequisite for
moving the Google token into the Keychain ([roadmap](roadmap.md)). The release
workflow and `package-release.sh` are prepared for it: add the secrets above and
the builds are signed with the hardened runtime, notarized with
`xcrun notarytool` and stapled.

## Google OAuth verification of the shared client

The shared client lives in the maintainer's Google Cloud project, published
**In production** but **unverified**. That means:

- users see “Google hasn't verified this app” on the consent screen;
- Google allows at most **100 users** over the lifetime of the project until it
  is verified (the counter is shown under Google Auth Platform → Audience →
  OAuth user cap, and can't be reset);
- the Google Tasks API scope `https://www.googleapis.com/auth/tasks` is a
  **sensitive** (not restricted) scope, so verification needs a review but no
  third-party security assessment.

To lift the cap and remove the warning:

1. **Branding.** In Google Auth Platform → Branding, keep the app name
   *Local Tasks Bridge*, add a logo (120 × 120 px), the support e-mail, the home
   page `https://siyuanj.github.io/local-tasks-bridge-site/`, the privacy policy
   `https://siyuanj.github.io/local-tasks-bridge-site/privacy/` and the authorized
   domain `siyuanj.github.io`. The home page must describe what the app does,
   link to the privacy policy and be publicly reachable without signing in.
   The privacy policy must say what Google data is accessed and how it is
   used, stored and shared, and include the Limited Use statement; the
   repository's [PRIVACY.md](../PRIVACY.md) is the long form of it — keep both
   in line with the app's actual behavior.
2. **Domain ownership.** Verify the site in
   [Google Search Console](https://search.google.com/search-console) with a
   Google account that is an Owner or Editor of the Cloud project. For a
   GitHub Pages site, add a URL-prefix property for
   `https://siyuanj.github.io/` and verify it with the HTML tag method in the
   site's layout. If Google insists on a domain property, use a custom domain
   for the pages.
3. **Data Access.** Add the scopes the app requests: `…/auth/tasks`, `openid`
   and `…/auth/userinfo.email`. For the Tasks scope, write a justification:
   the app performs two-way sync — it creates, edits, completes and deletes
   tasks — so the read-only scope is not enough; data is processed only on the
   user's Mac and never sent to the developer.
4. **Demo video.** Record a short video and upload it to YouTube as unlisted.
   It should show the setup assistant choosing the shared client; the Google
   consent screen in English with the OAuth client ID visible in the browser's
   address bar; the scopes being granted; a task syncing in both directions;
   and where data is stored (only on the Mac).
5. **Submit** in Google Auth Platform → Verification Center and answer
   follow-up e-mails from Google's review team promptly. Brand verification
   usually takes a few business days; sensitive-scope review can take several
   weeks.

After verification, the warning disappears and the user cap is lifted. Any
change to the scopes, app name, logo or domains needs verification again.

## Google Tasks API quota

All users of the shared client share one project quota — by default about
**50,000 requests per day**. The engine therefore polls at most every 5
minutes for shared-client users and skips verification reads in idle cycles: a
user with one synced list needs roughly 580 requests a day, with three lists
about 1,150, plus a few for each burst of local edits
([quota math](configuration.md#sync-interval-and-google-quota)). So the default
quota covers only a few dozen active users.

- Watch usage under APIs & Services → Google Tasks API → Metrics and Quotas
  (`https://console.cloud.google.com/apis/api/tasks.googleapis.com/quotas`), and
  consider an alert in Cloud Monitoring before the daily limit is reached.
- Request an increase from the Quotas page with a short justification (number
  of users, lists per user, interval). Google may ask for a billing account to
  be linked before granting higher quotas, even though the Tasks API itself is
  free of charge.
- When the quota is exhausted, requests fail with HTTP 429 or 403 until the
  quota resets at midnight Pacific Time; the bridge reports failed cycles and
  recovers by itself afterwards. Users with their own client are unaffected.

## Making the repository public

- [ ] **Author e-mail in the history.** The fork's commits carry the author
      e-mail address used on this Mac. Publishing the repository publishes it.
      Either accept that, or rewrite the history before the first public push
      (for example with `git filter-repo --mailmap`) and use the GitHub
      `noreply` address from then on (`git config user.email
      <id>+siyuanj@users.noreply.github.com`, plus “Keep my email addresses
      private” in GitHub settings). Rewriting must happen before anyone clones
      the public repository.
- [ ] **Secret scan of the full history**, not just the current tree:

      ```bash
      gitleaks git --redact -v .
      trufflehog git file://. --results=verified,unknown
      git log --all --name-only --format= | sort -u \
        | grep -Ei 'client_secret|credentials|token|state\.json|status\.json|\.log$'
      ```

      A scan on 2026-10-01 found nothing; run it again right before publishing.
- [ ] **Personal data in the history:** search old commits for absolute paths,
      real task titles and e-mail addresses (for example
      `git log -p --all | grep -nE '/Users/[^/]+/'`).
- [ ] **Tags:** don't push local deployment tags such as
      `prod/icloud-reminders-google-sync/…`; push only `vX.Y.Z` tags.
- [ ] **Links:** the issue template's security link
      (`.github/ISSUE_TEMPLATE/config.yml`) and every documentation link must
      point to `siyuanj/local-tasks-bridge`.
- [ ] **Repository settings:** description, website
      (`https://siyuanj.github.io/local-tasks-bridge-site/`), topics (`macos`,
      `apple-reminders`, `google-tasks`, `sync`, `menu-bar-app`).
- [ ] **Security settings:** enable *Private vulnerability reporting*
      (Settings → Security → Advisories), Dependabot alerts, secret scanning
      and push protection.
- [ ] **Branch protection** for `main`: require pull requests and green CI, and
      block force pushes.
- [ ] **Actions:** keep actions pinned to full commit SHAs and workflow
      permissions minimal; make sure secrets are used only by the release
      workflow on tags.
- [ ] **Change the visibility** (Settings → General → Danger Zone).
- [ ] **Publish v1.0.0** and test the one-line installer and the raw
      `install.sh` URL from a clean macOS user account.
- [ ] **Website pages:** the home page and privacy policy live in the separate public repository
      [siyuanj/local-tasks-bridge-site](https://github.com/siyuanj/local-tasks-bridge-site) (GitHub Pages,
      `https://siyuanj.github.io/local-tasks-bridge-site/`). Keep them in line with
      [PRIVACY.md](../PRIVACY.md); they are the URLs registered in the Google OAuth branding.

## A Homebrew tap (later)

The cask template lives in `packaging/homebrew/local-tasks-bridge.rb`. Render
it for a release with the version and the checksums of that release:

```bash
packaging/homebrew/update-cask.sh --version X.Y.Z --sums path/to/SHA256SUMS
```

By default the script uses the `VERSION` file and `dist/SHA256SUMS` and writes
`dist/local-tasks-bridge.rb` (`--output` changes that). Commit the result to a
tap repository such as `siyuanj/homebrew-tap` as `Casks/local-tasks-bridge.rb`;
users then install with `brew install --cask siyuanj/tap/local-tasks-bridge`.

The template works with the ad-hoc-signed 1.0 builds — its caveats explain the
Gatekeeper step, since Homebrew quarantines what it downloads — but a tap is
best announced once builds are notarized. It quits the app on `brew uninstall`
and removes the login item, settings and logs only on `brew uninstall --zap`,
so a `brew upgrade` doesn't remove the login item. Edit the template rather
than writing a cask by hand.

