import Foundation

/// Fixed names, links, and per-user locations shared by the whole app.
enum AppInfo {
    static let bundleIdentifier = "io.github.siyuanj.LocalTasksBridge"
    static let launchAgentLabel = "io.github.siyuanj.local-tasks-bridge"
    static let productName = "Local Tasks Bridge"
    /// Posted by a second copy of the app to ask the running one to show itself.
    static let showRequestNotification = Notification.Name("io.github.siyuanj.LocalTasksBridge.showRequest")

    static let repositoryURL = URL(string: "https://github.com/siyuanj/local-tasks-bridge")!
    static let latestReleaseAPIURL = URL(string: "https://api.github.com/repos/siyuanj/local-tasks-bridge/releases/latest")!
    static let releasesURL = URL(string: "https://github.com/siyuanj/local-tasks-bridge/releases")!
    static let googleTasksURL = URL(string: "https://tasks.google.com")!
    static let privacyPolicyURL = URL(string: "https://siyuanj.github.io/local-tasks-bridge/privacy/")!
    static let remindersBundleIdentifier = "com.apple.reminders"

    static var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
    }

    /// The localization the app is actually running in ("en" or "zh-Hans").
    static var usesChinese: Bool {
        Bundle.main.preferredLocalizations.first?.lowercased().hasPrefix("zh") ?? false
    }

    /// Value of LTB_LANG for engine processes (contract section 3).
    static var engineLanguage: String { usesChinese ? "zh" : "en" }

    /// Locale for dates and relative times, matching the app's localization.
    static var displayLocale: Locale {
        Locale(identifier: Bundle.main.preferredLocalizations.first ?? "en")
    }

    static var helpURL: URL {
        usesChinese
            ? repositoryURL.appendingPathComponent("blob/main/README.zh-CN.md")
            : URL(string: repositoryURL.absoluteString + "#readme")!
    }

    static var googleCloudSetupURL: URL {
        repositoryURL.appendingPathComponent(
            usesChinese ? "blob/main/docs/google-cloud-setup.zh-CN.md" : "blob/main/docs/google-cloud-setup.md"
        )
    }

    static var bundleURL: URL { Bundle.main.bundleURL }

    /// Gatekeeper runs quarantined apps that were never moved from a randomized,
    /// read-only location; a login item pointing there would break after restart.
    static var runsFromTemporaryLocation: Bool {
        let path = bundleURL.path
        return path.contains("/AppTranslocation/") || path.hasPrefix("/Volumes/")
    }

    /// True when launchd started this process from the login item.
    static var isLaunchAgentJob: Bool {
        ProcessInfo.processInfo.environment["XPC_SERVICE_NAME"] == launchAgentLabel
    }
}

/// Per-user files the app reads or opens (contract section 1).
struct AppPaths {
    let configDirectory: URL
    let configFile: URL
    let logDirectory: URL

    var appLog: URL { logDirectory.appendingPathComponent("app.log") }
    var engineLog: URL { logDirectory.appendingPathComponent("engine.log") }
    var commandLineToolLink: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/ltb")
    }

    /// Mirrors the engine: XDG_CONFIG_HOME or ~/.config, and LTB_LOG_DIR for tests.
    static func current(environment: [String: String] = ProcessInfo.processInfo.environment) -> AppPaths {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let configBase: URL
        if let xdg = environment["XDG_CONFIG_HOME"], !xdg.isEmpty {
            configBase = URL(fileURLWithPath: (xdg as NSString).expandingTildeInPath, isDirectory: true)
        } else {
            configBase = home.appendingPathComponent(".config", isDirectory: true)
        }
        let configDirectory = configBase.appendingPathComponent("local-tasks-bridge", isDirectory: true)
        let logDirectory: URL
        if let override = environment["LTB_LOG_DIR"], !override.isEmpty {
            logDirectory = URL(fileURLWithPath: (override as NSString).expandingTildeInPath, isDirectory: true)
        } else {
            logDirectory = home.appendingPathComponent("Library/Logs/LocalTasksBridge", isDirectory: true)
        }
        return AppPaths(
            configDirectory: configDirectory,
            configFile: configDirectory.appendingPathComponent("config.json"),
            logDirectory: logDirectory
        )
    }
}
