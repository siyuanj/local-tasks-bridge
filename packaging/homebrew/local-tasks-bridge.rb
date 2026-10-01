# Homebrew cask template for Local Tasks Bridge, meant for the tap
# siyuanj/homebrew-tap (file Casks/local-tasks-bridge.rb).
#
# The @...@ values are filled in from a release's SHA256SUMS; do not edit them
# by hand. After publishing a release, render the cask with:
#
#   gh release download v1.2.3 --repo siyuanj/local-tasks-bridge --pattern SHA256SUMS --dir dist
#   packaging/homebrew/update-cask.sh --version 1.2.3 --sums dist/SHA256SUMS \
#     --output ../homebrew-tap/Casks/local-tasks-bridge.rb
cask "local-tasks-bridge" do
  arch arm: "arm64", intel: "x86_64"

  version "@VERSION@"
  sha256 arm:   "@SHA256_ARM64@",
         intel: "@SHA256_X86_64@"

  url "https://github.com/siyuanj/local-tasks-bridge/releases/download/v#{version}/LocalTasksBridge-macos-#{arch}.zip"
  name "Local Tasks Bridge"
  desc "Local-first sync between Apple Reminders and Google Tasks"
  homepage "https://github.com/siyuanj/local-tasks-bridge"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on macos: :ventura

  app "Local Tasks Bridge.app"
  binary "#{appdir}/Local Tasks Bridge.app/Contents/Resources/bin/ltb"

  # Quit the app before its bundle is replaced or removed. The login item is
  # left alone so `brew upgrade` keeps syncing at the next login.
  uninstall quit: "io.github.siyuanj.LocalTasksBridge"

  zap launchctl: "io.github.siyuanj.local-tasks-bridge",
      trash:     [
        "~/.config/local-tasks-bridge",
        "~/Library/LaunchAgents/io.github.siyuanj.local-tasks-bridge.plist",
        "~/Library/Logs/LocalTasksBridge",
      ]

  caveats <<~EOS
    Local Tasks Bridge #{version} is ad-hoc signed and not notarized by Apple.
    If macOS says the app cannot be opened, open System Settings > Privacy &
    Security and click "Open Anyway", or remove the quarantine attribute:

      xattr -dr com.apple.quarantine "#{appdir}/Local Tasks Bridge.app"

    `brew upgrade` quits the app; open Local Tasks Bridge again afterwards
    (or log out and back in) to resume syncing.

    To stop syncing for good, choose Uninstall in the app (or run
    `ltb uninstall --yes`) before `brew uninstall`. `brew uninstall --zap`
    also deletes the settings, the sync map, the login item, and the logs.
  EOS
end
