import AppKit
import Combine

/// What the menu bar icon shows. Each state is a template SF Symbol.
enum MenuBarIconState: Equatable {
    case healthy
    case syncing
    case attention
    case paused
    case setupNeeded
    case idle

    var symbolName: String {
        switch self {
        case .healthy: return "arrow.triangle.2.circlepath.circle"
        case .syncing: return "arrow.triangle.2.circlepath"
        case .attention: return "exclamationmark.arrow.triangle.2.circlepath"
        case .paused: return "pause.circle"
        case .setupNeeded: return "gearshape"
        case .idle: return "arrow.triangle.2.circlepath.circle"
        }
    }

    var accessibilityLabel: String {
        switch self {
        case .healthy: return NSLocalizedString("Local Tasks Bridge: in sync", comment: "Menu bar icon accessibility label")
        case .syncing: return NSLocalizedString("Local Tasks Bridge: syncing", comment: "Menu bar icon accessibility label")
        case .attention: return NSLocalizedString("Local Tasks Bridge: needs attention", comment: "Menu bar icon accessibility label")
        case .paused: return NSLocalizedString("Local Tasks Bridge: paused", comment: "Menu bar icon accessibility label")
        case .setupNeeded: return NSLocalizedString("Local Tasks Bridge: setup needed", comment: "Menu bar icon accessibility label")
        case .idle: return AppInfo.productName
        }
    }

    @MainActor
    static func current(for model: AppModel) -> MenuBarIconState {
        switch model.availability {
        case .pythonMissing, .engineMissing:
            return .setupNeeded
        case .locating:
            return .idle
        case .ready:
            break
        }
        guard let status = model.status else {
            return model.statusError == nil ? .idle : .attention
        }
        if !status.isSetupCompleted {
            return .setupNeeded
        }
        if model.cycleInProgress || status.condition == "running" {
            return .syncing
        }
        switch status.condition {
        case "healthy":
            return .healthy
        case "paused":
            return .paused
        case "setup_required":
            return .setupNeeded
        case "agent_stopped":
            // The app runs the loop itself while it is open.
            return model.supervisorPhase == .running || status.loopRunning == true ? .idle : .attention
        case "auth_required", "account_binding_required", "mutation_approval_pending",
             "mutation_blocked", "failed", "status_unreadable":
            return .attention
        default:
            // "attention" (a check passed, the next full sync is still to come),
            // "never_synced", and "unknown" are not problems in themselves.
            return .idle
        }
    }
}

/// The menu bar item and its menu.
@MainActor
final class StatusMenuController: NSObject, NSMenuDelegate {
    private let model: AppModel
    private let windows: WindowCoordinator
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()
    private var subscriptions = Set<AnyCancellable>()
    private var headlineItem: NSMenuItem?
    private var detailItem: NSMenuItem?

    init(model: AppModel, windows: WindowCoordinator) {
        self.model = model
        self.windows = windows
        super.init()
        menu.delegate = self
        menu.autoenablesItems = false
        statusItem.menu = menu
        updateIcon()

        model.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.updateIcon()
                self?.updateHeader()
            }
            .store(in: &subscriptions)
    }

    // MARK: Icon

    private func updateIcon() {
        let state = MenuBarIconState.current(for: model)
        guard let button = statusItem.button else {
            return
        }
        let image = NSImage(systemSymbolName: state.symbolName, accessibilityDescription: state.accessibilityLabel)
            ?? NSImage(systemSymbolName: "checklist", accessibilityDescription: state.accessibilityLabel)
        image?.isTemplate = true
        button.image = image
        button.toolTip = headline
    }

    // MARK: Menu

    func menuNeedsUpdate(_ menu: NSMenu) {
        rebuild()
    }

    func menuWillOpen(_ menu: NSMenu) {
        model.scheduleStatusRefresh(after: 0)
    }

    private func rebuild() {
        menu.removeAllItems()

        let headline = NSMenuItem(title: self.headline, action: nil, keyEquivalent: "")
        headline.isEnabled = false
        menu.addItem(headline)
        headlineItem = headline
        let detail = NSMenuItem(title: detailText, action: nil, keyEquivalent: "")
        detail.isEnabled = false
        menu.addItem(detail)
        detailItem = detail
        menu.addItem(.separator())

        let ready = model.client != nil && model.status?.isSetupCompleted == true
        let paused = model.status?.isPaused ?? false
        menu.addItem(item(NSLocalizedString("Sync Now", comment: "Menu item"), #selector(syncNow), enabled: ready && !paused))
        menu.addItem(item(
            paused ? NSLocalizedString("Resume Sync", comment: "Menu item") : NSLocalizedString("Pause Sync", comment: "Menu item"),
            #selector(togglePause),
            enabled: ready
        ))
        if model.needsApproval {
            menu.addItem(item(NSLocalizedString("Review Pending Changes…", comment: "Menu item"), #selector(reviewChanges)))
        }
        if model.needsGoogleSignIn {
            menu.addItem(item(NSLocalizedString("Reconnect Google…", comment: "Menu item"), #selector(reconnectGoogle)))
        }
        menu.addItem(.separator())

        menu.addItem(item(
            model.needsSetup ? NSLocalizedString("Finish Setup…", comment: "Menu item") : NSLocalizedString("Setup Assistant…", comment: "Menu item"),
            #selector(openSetup)
        ))
        menu.addItem(item(NSLocalizedString("Settings…", comment: "Menu item"), #selector(openSettings), key: ",", enabled: model.client != nil))
        menu.addItem(item(NSLocalizedString("Open Google Tasks", comment: "Menu item"), #selector(openGoogleTasks)))
        menu.addItem(item(NSLocalizedString("Open Reminders", comment: "Menu item"), #selector(openReminders)))
        menu.addItem(.separator())

        menu.addItem(item(NSLocalizedString("Open Logs", comment: "Menu item"), #selector(openLogs)))
        menu.addItem(item(NSLocalizedString("Open Data Folder", comment: "Menu item"), #selector(openDataFolder)))
        menu.addItem(item(NSLocalizedString("Copy Diagnostics", comment: "Menu item"), #selector(copyDiagnostics), enabled: model.client != nil))
        menu.addItem(item(NSLocalizedString("Check for Updates…", comment: "Menu item"), #selector(checkForUpdates)))
        menu.addItem(item(NSLocalizedString("Help", comment: "Menu item"), #selector(openHelp)))
        menu.addItem(item(NSLocalizedString("About Local Tasks Bridge", comment: "Menu item"), #selector(showAbout)))
        menu.addItem(.separator())
        menu.addItem(item(NSLocalizedString("Quit Local Tasks Bridge", comment: "Menu item"), #selector(quit), key: "q"))
    }

    private func updateHeader() {
        headlineItem?.title = headline
        detailItem?.title = detailText
    }

    private func item(_ title: String, _ action: Selector, key: String = "", enabled: Bool = true) -> NSMenuItem {
        let menuItem = NSMenuItem(title: title, action: action, keyEquivalent: key)
        menuItem.target = self
        menuItem.isEnabled = enabled
        return menuItem
    }

    private var headline: String {
        switch model.availability {
        case .locating:
            return NSLocalizedString("Starting…", comment: "Menu status headline")
        case .pythonMissing:
            return NSLocalizedString("Python 3.9 or newer is required.", comment: "Engine error")
        case .engineMissing:
            return NSLocalizedString("Local Tasks Bridge is incomplete. Reinstall it.", comment: "Menu status headline")
        case .ready:
            break
        }
        if let status = model.status {
            if !status.isSetupCompleted {
                return NSLocalizedString("Setup isn’t finished yet", comment: "Menu status headline")
            }
            if model.cycleInProgress {
                return NSLocalizedString("Syncing…", comment: "Menu status headline")
            }
            if let headline = status.headline, !headline.isEmpty {
                return headline
            }
        } else if let error = model.statusError {
            return error.message
        }
        return NSLocalizedString("Checking status…", comment: "Menu status headline")
    }

    private var detailText: String {
        guard let status = model.status, status.isSetupCompleted else {
            return NSLocalizedString("Choose Finish Setup… to get started.", comment: "Menu status detail")
        }
        let state = MenuBarIconState.current(for: model)
        if state == .attention || state == .paused || status.condition == "attention",
           let action = status.action, !action.isEmpty {
            return action
        }
        return RelativeTime.lastSynced(status.lastSuccessDate)
    }

    // MARK: Actions

    @objc private func syncNow() {
        Task {
            do {
                try await model.syncNow()
            } catch {
                Alerts.show(error)
            }
        }
    }

    @objc private func togglePause() {
        let paused = model.status?.isPaused ?? false
        Task {
            do {
                try await model.setPaused(!paused)
            } catch {
                Alerts.show(error)
            }
        }
    }

    @objc private func reviewChanges() { windows.showApprovals() }
    @objc private func reconnectGoogle() {
        // A changed account needs a rebuilt sync map; an expired sign-in only a new sign-in.
        let action: SettingsModel.Action = model.status?.condition == "account_binding_required" ? .rebuild : .reconnect
        windows.showSettings(tab: .google, action: action)
    }
    @objc private func openSetup() { windows.showSetup() }
    @objc private func openSettings() { windows.showSettings() }
    @objc private func openGoogleTasks() { NSWorkspace.shared.open(AppInfo.googleTasksURL) }
    @objc private func openReminders() { SystemActions.openReminders() }
    @objc private func openLogs() { SystemActions.openLogs(paths: model.paths) }
    @objc private func openDataFolder() { SystemActions.openDataFolder(paths: model.paths) }
    @objc private func openHelp() { NSWorkspace.shared.open(AppInfo.helpURL) }
    @objc private func showAbout() { SystemActions.showAboutPanel() }
    @objc private func quit() { NSApp.terminate(nil) }

    @objc private func copyDiagnostics() {
        Task { await Diagnostics.copyToPasteboard(model: model) }
    }

    @objc private func checkForUpdates() {
        Task { await UpdateChecker.checkAndReport(proxy: model.config?.proxy) }
    }
}

enum RelativeTime {
    static func lastSynced(_ date: Date?, now: Date = Date()) -> String {
        guard let date else {
            return NSLocalizedString("Not synced yet", comment: "Menu status detail")
        }
        if now.timeIntervalSince(date) < 60 {
            return NSLocalizedString("Last synced just now", comment: "Menu status detail")
        }
        let formatter = RelativeDateTimeFormatter()
        formatter.locale = AppInfo.displayLocale
        formatter.unitsStyle = .full
        return String(
            format: NSLocalizedString("Last synced %@", comment: "Menu status detail; %@ is a relative time such as “2 minutes ago”"),
            formatter.localizedString(for: date, relativeTo: now)
        )
    }
}
