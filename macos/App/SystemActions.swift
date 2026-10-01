import AppKit

/// Modal alerts for menu actions that have no window of their own.
@MainActor
enum Alerts {
    static func show(_ error: Error) {
        if let engineError = error as? EngineError, engineError.isCancellation {
            return
        }
        let message = (error as? EngineError)?.message ?? error.localizedDescription
        present(
            title: NSLocalizedString("Local Tasks Bridge couldn’t do that", comment: "Error alert title"),
            message: message,
            style: .warning
        )
    }

    static func inform(title: String, message: String) {
        present(title: title, message: message, style: .informational)
    }

    /// Returns true when the person chose `confirmTitle`.
    static func confirm(title: String, message: String, confirmTitle: String, destructive: Bool = false) -> Bool {
        let alert = NSAlert()
        alert.alertStyle = destructive ? .critical : .warning
        alert.messageText = title
        alert.informativeText = message
        let confirm = alert.addButton(withTitle: confirmTitle)
        confirm.hasDestructiveAction = destructive
        alert.addButton(withTitle: NSLocalizedString("Cancel", comment: "Button"))
        NSApp.activate(ignoringOtherApps: true)
        return alert.runModal() == .alertFirstButtonReturn
    }

    private static func present(title: String, message: String, style: NSAlert.Style) {
        let alert = NSAlert()
        alert.alertStyle = style
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: NSLocalizedString("OK", comment: "Button"))
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }
}

/// Small actions that open other apps, folders, or panels.
@MainActor
enum SystemActions {
    static func openReminders() {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: AppInfo.remindersBundleIdentifier) else {
            return
        }
        NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
    }

    static func openLogs(paths: AppPaths) {
        let fileManager = FileManager.default
        if fileManager.fileExists(atPath: paths.engineLog.path) {
            NSWorkspace.shared.activateFileViewerSelecting([paths.engineLog])
        } else if fileManager.fileExists(atPath: paths.logDirectory.path) {
            NSWorkspace.shared.open(paths.logDirectory)
        } else {
            Alerts.inform(
                title: NSLocalizedString("No logs yet", comment: "Alert title"),
                message: NSLocalizedString("Logs appear here after the first sync.", comment: "Alert message")
            )
        }
    }

    static func openDataFolder(paths: AppPaths) {
        if FileManager.default.fileExists(atPath: paths.configDirectory.path) {
            NSWorkspace.shared.open(paths.configDirectory)
        } else {
            Alerts.inform(
                title: NSLocalizedString("No data folder yet", comment: "Alert title"),
                message: NSLocalizedString("The data folder is created when you finish setup.", comment: "Alert message")
            )
        }
    }

    static func showAboutPanel() {
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = .center
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize),
            .foregroundColor: NSColor.secondaryLabelColor,
            .paragraphStyle: paragraph,
        ]
        let credits = NSMutableAttributedString(
            string: NSLocalizedString("Syncs Apple Reminders with Google Tasks, on this Mac only.", comment: "About panel") + "\n\n"
                + NSLocalizedString("MIT License. A fork of syncweave-labs/reminders-task-bridge, maintained by Siyuan Jiang.", comment: "About panel")
                + "\n",
            attributes: attributes
        )
        var linkAttributes = attributes
        linkAttributes[.link] = AppInfo.repositoryURL
        credits.append(NSAttributedString(string: AppInfo.repositoryURL.absoluteString, attributes: linkAttributes))

        NSApp.activate(ignoringOtherApps: true)
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: AppInfo.productName,
            .applicationVersion: AppInfo.version,
            .version: "",
            .credits: credits,
        ])
    }
}

/// `~/.local/bin/ltb`, a symlink to the wrapper inside the app.
enum CommandLineTool {
    enum InstallError: LocalizedError {
        case occupied(String)

        var errorDescription: String? {
            switch self {
            case .occupied(let path):
                return String(
                    format: NSLocalizedString("%@ already exists and is not a link to Local Tasks Bridge. Remove it first.", comment: "Command-line tool install error; %@ is a path"),
                    path
                )
            }
        }
    }

    static var wrapper: URL {
        AppInfo.bundleURL.appendingPathComponent("Contents/Resources/bin/ltb")
    }

    static func isInstalled(at link: URL) -> Bool {
        guard let destination = try? FileManager.default.destinationOfSymbolicLink(atPath: link.path) else {
            return false
        }
        return URL(fileURLWithPath: destination).standardizedFileURL == wrapper.standardizedFileURL
    }

    static func install(at link: URL) throws {
        let fileManager = FileManager.default
        try fileManager.createDirectory(
            at: link.deletingLastPathComponent(),
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o755]
        )
        if let attributes = try? fileManager.attributesOfItem(atPath: link.path) {
            guard attributes[.type] as? FileAttributeType == .typeSymbolicLink else {
                throw InstallError.occupied(link.path)
            }
            try fileManager.removeItem(at: link)
        }
        try fileManager.createSymbolicLink(at: link, withDestinationURL: wrapper)
    }

    /// Removes the link if it points into this app (used when uninstalling).
    static func removeIfInstalled(at link: URL) {
        if isInstalled(at: link) {
            try? FileManager.default.removeItem(at: link)
        }
    }
}

/// Copy Diagnostics: `doctor --json` plus app details, without the home folder path.
@MainActor
enum Diagnostics {
    static func copyToPasteboard(model: AppModel) async {
        guard let client = model.client else {
            return
        }
        do {
            let doctor = try await client.doctor()
            let pasteboard = NSPasteboard.general
            pasteboard.clearContents()
            pasteboard.setString(report(doctor: doctor, model: model, runtime: client.runtime), forType: .string)
            Alerts.inform(
                title: NSLocalizedString("Diagnostics copied", comment: "Alert title"),
                message: NSLocalizedString("Paste them into a bug report. They contain no reminder or task titles.", comment: "Alert message")
            )
        } catch {
            Alerts.show(error)
        }
    }

    static func report(doctor: Data, model: AppModel, runtime: EngineRuntime) -> String {
        var architecture = "unknown"
        #if arch(arm64)
        architecture = "arm64"
        #elseif arch(x86_64)
        architecture = "x86_64"
        #endif
        var lines = [
            "\(AppInfo.productName) \(AppInfo.version)",
            "macOS \(ProcessInfo.processInfo.operatingSystemVersionString), \(architecture)",
            "App: \(AppInfo.bundleURL.path)",
            "Python: \(runtime.python.path)",
            "Language: \(Bundle.main.preferredLocalizations.first ?? "en")",
            "Background loop: \(model.supervisorPhase)",
            "",
        ]
        if let object = try? JSONSerialization.jsonObject(with: doctor),
           let pretty = try? JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]) {
            lines.append(String(decoding: pretty, as: UTF8.self))
        } else {
            lines.append(String(decoding: doctor, as: UTF8.self))
        }
        return lines.joined(separator: "\n").replacingOccurrences(of: NSHomeDirectory(), with: "~")
    }
}
