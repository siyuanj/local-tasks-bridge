import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let options: LaunchOptions
    private let model: AppModel
    private let windows: WindowCoordinator
    private var statusMenu: StatusMenuController?
    private var terminationRequested = false

    init(options: LaunchOptions, paths: AppPaths, log: AppLog) {
        self.options = options
        self.model = AppModel(paths: paths, log: log)
        self.windows = WindowCoordinator(model: model)
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        MainMenu.install(target: self)
        statusMenu = StatusMenuController(model: model, windows: windows)
        model.showApprovals = { [weak self] in
            self?.windows.showApprovals()
        }
        DistributedNotificationCenter.default().addObserver(
            self,
            selector: #selector(showRequested(_:)),
            name: AppInfo.showRequestNotification,
            object: nil,
            suspensionBehavior: .deliverImmediately
        )
        Task {
            await model.start()
            if options.showSettings && !model.needsSetup {
                windows.showSettings()
            } else if !options.background && model.needsSetup {
                // At login (--background) setup waits for "Finish Setup…" in the menu.
                windows.showSetup()
            }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !terminationRequested else {
            return .terminateLater
        }
        terminationRequested = true
        // Let a sync cycle in progress finish (up to 30 s) before quitting.
        Task {
            await model.prepareToQuit()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    @objc private func showRequested(_ notification: Notification) {
        showMainWindow()
    }

    @objc func showAbout(_ sender: Any?) {
        SystemActions.showAboutPanel()
    }

    @objc func showSettingsWindow(_ sender: Any?) {
        if model.needsSetup {
            windows.showSetup()
        } else {
            windows.showSettings()
        }
    }

    /// What "open the app" means for a menu bar app: setup until it is done, then Settings.
    private func showMainWindow() {
        if model.needsSetup {
            windows.showSetup()
        } else {
            windows.showSettings()
        }
    }
}
