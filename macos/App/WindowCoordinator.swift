import AppKit
import SwiftUI

/// Opens and reuses the app's windows. While any window is open the app shows
/// in the Dock and the app switcher, so a window that went behind the browser
/// during Google sign-in is easy to find again.
@MainActor
final class WindowCoordinator: NSObject, NSWindowDelegate {
    enum Kind: Hashable {
        case setup, settings, approvals, uninstall
    }

    private let model: AppModel
    private var windows: [Kind: NSWindow] = [:]
    private var cancelWork: [Kind: @MainActor () -> Void] = [:]
    /// Per window: whether it is busy with something that must not be interrupted.
    private var busy: [Kind: @MainActor () -> Bool] = [:]
    private var approvalsModel: ApprovalsModel?
    private var settingsModel: SettingsModel?

    init(model: AppModel) {
        self.model = model
    }

    func showSetup() {
        if bringToFront(.setup) {
            return
        }
        let setup = SetupModel(app: model)
        setup.close = { [weak self] in self?.close(.setup) }
        busy[.setup] = { setup.working && !setup.workCancellable }
        present(
            .setup,
            title: NSLocalizedString("Local Tasks Bridge Setup", comment: "Window title"),
            view: SetupView(model: setup),
            resizable: false,
            cancel: setup.cancelWork
        )
    }

    /// Opens Settings, optionally on a tab and starting an action there.
    func showSettings(tab: SettingsModel.Tab? = nil, action: SettingsModel.Action = .none) {
        if let settingsModel, bringToFront(.settings) {
            settingsModel.open(tab: tab, action: action)
            return
        }
        let settings = SettingsModel(app: model)
        settings.showUninstall = { [weak self] in self?.showUninstall() }
        settings.open(tab: tab, action: action)
        settingsModel = settings
        busy[.settings] = { settings.rebuildModel?.writing ?? false }
        present(
            .settings,
            title: NSLocalizedString("Local Tasks Bridge Settings", comment: "Window title"),
            view: SettingsView(model: settings),
            resizable: false,
            cancel: settings.cancelWork
        )
    }

    /// Opens Review Pending Changes, or reloads it if it is already open.
    func showApprovals() {
        if let approvalsModel, bringToFront(.approvals) {
            if !approvalsModel.working {
                approvalsModel.load()
            }
            return
        }
        let approvals = ApprovalsModel(app: model)
        approvals.close = { [weak self] in self?.close(.approvals) }
        approvalsModel = approvals
        busy[.approvals] = { approvals.working }
        present(
            .approvals,
            title: NSLocalizedString("Review Pending Changes", comment: "Window title"),
            view: ApprovalsView(model: approvals),
            resizable: true,
            cancel: approvals.cancelWork
        )
    }

    func showUninstall() {
        if bringToFront(.uninstall) {
            return
        }
        let uninstall = UninstallModel(app: model)
        uninstall.close = { [weak self] in self?.close(.uninstall) }
        busy[.uninstall] = { uninstall.working }
        present(
            .uninstall,
            title: NSLocalizedString("Uninstall Local Tasks Bridge", comment: "Window title"),
            view: UninstallView(model: uninstall),
            resizable: false,
            cancel: {}
        )
    }

    func close(_ kind: Kind) {
        windows[kind]?.close()
    }

    // MARK: NSWindowDelegate

    /// Write commands always run to the end, so their window stays open meanwhile.
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        guard let kind = windows.first(where: { $0.value === sender })?.key else {
            return true
        }
        if model.client?.writeInProgress == true || busy[kind]?() == true {
            NSSound.beep()
            return false
        }
        return true
    }

    func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow,
              let kind = windows.first(where: { $0.value === window })?.key else {
            return
        }
        cancelWork[kind]?()
        cancelWork[kind] = nil
        busy[kind] = nil
        windows[kind] = nil
        if kind == .approvals {
            approvalsModel = nil
        }
        if kind == .settings {
            settingsModel = nil
        }
        if windows.isEmpty {
            NSApp.setActivationPolicy(.accessory)
        }
    }

    // MARK: Helpers

    private func bringToFront(_ kind: Kind) -> Bool {
        guard let window = windows[kind] else {
            return false
        }
        activate()
        window.makeKeyAndOrderFront(nil)
        return true
    }

    private func present<Content: View>(
        _ kind: Kind,
        title: String,
        view: Content,
        resizable: Bool,
        cancel: @escaping @MainActor () -> Void
    ) {
        var style: NSWindow.StyleMask = [.titled, .closable, .miniaturizable]
        if resizable {
            style.insert(.resizable)
        }
        let controller = NSHostingController(rootView: view)
        let window = NSWindow(contentViewController: controller)
        window.styleMask = style
        window.title = title
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.center()
        windows[kind] = window
        cancelWork[kind] = cancel
        activate()
        window.makeKeyAndOrderFront(nil)
    }

    private func activate() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}
