import AppKit
import UniformTypeIdentifiers
import UserNotifications

/// State and actions of the Settings window. General settings apply at once;
/// Lists, Safety, and Network keep a draft until Apply.
@MainActor
final class SettingsModel: ObservableObject {
    enum Tab: Hashable {
        case general, lists, safety, google, network, advanced
    }

    /// What to start when Settings opens from the menu.
    enum Action {
        case none
        case reconnect
        case rebuild
    }

    let app: AppModel
    let lists: ListSelectionModel
    /// Opens the uninstall window; set by the window coordinator.
    var showUninstall: () -> Void = {}

    @Published var tab: Tab = .general
    @Published private(set) var saved = BridgeConfig()
    @Published private(set) var errorMessage: String?
    @Published private(set) var saving = false
    /// config.json could not be read; only "Reset Settings…" helps.
    @Published private(set) var configUnreadable = false

    // General
    @Published private(set) var startAtLogin = false
    @Published private(set) var updatingLoginItem = false
    @Published private(set) var language = "auto"
    @Published private(set) var notificationsOn = true
    @Published private(set) var notificationsDenied = false
    @Published private(set) var interval = 60

    // Drafts
    @Published var bidirectional = true
    @Published var deleteStale = true
    @Published var maxChanges = 25
    @Published var maxRatioPercent = 25
    @Published var conflictPolicy = "newer_wins"
    @Published var proxy = ProxyChoice()

    // Google
    @Published private(set) var accountEmail: String?
    @Published private(set) var accountProblem: String?
    @Published private(set) var checkingAccount = false
    @Published private(set) var signingIn = false
    @Published private(set) var clientStatus: OAuthClientStatus?
    @Published private(set) var importedClientHint: String?
    @Published private(set) var needsReconnect = false

    // Advanced
    @Published private(set) var commandLineToolInstalled = false
    @Published private(set) var commandLineToolMessage: String?

    private var signInTask: Task<Void, Never>?
    private var languageAtOpen: String?

    init(app: AppModel) {
        self.app = app
        self.lists = ListSelectionModel(app: app)
        self.commandLineToolInstalled = CommandLineTool.isInstalled(at: app.paths.commandLineToolLink)
    }

    /// The "pair accounts again" sheet, while it is shown.
    @Published private(set) var rebuildModel: RebuildModel?

    /// Switches to `tab` and starts `action`.
    func open(tab: Tab?, action: Action = .none) {
        if let tab {
            self.tab = tab
        }
        switch action {
        case .reconnect where !signingIn:
            reconnect()
        case .rebuild:
            openRebuild()
        default:
            break
        }
    }

    func openRebuild() {
        guard rebuildModel == nil else {
            return
        }
        let rebuild = RebuildModel(app: app)
        rebuild.close = { [weak self] in self?.closeRebuild() }
        rebuildModel = rebuild
    }

    func closeRebuild() {
        rebuildModel?.cancelWork()
        rebuildModel = nil
        app.scheduleStatusRefresh()
    }

    // MARK: Loading

    func load() async {
        guard let client = app.client else {
            return
        }
        do {
            adopt(try await client.configShow())
            configUnreadable = false
        } catch let error as EngineError where error.code == EngineErrorCode.configInvalid {
            configUnreadable = true
            show(error)
        } catch {
            show(error)
        }
        if let status = try? await app.currentStatus() {
            startAtLogin = status.agent?.installed ?? false
        }
        clientStatus = try? await client.clientStatus()
        await refreshNotificationPermission()
        await lists.load(preselect: saved.includeLists ?? [])
    }

    private func adopt(_ config: BridgeConfig) {
        saved = config
        language = config.language ?? "auto"
        if languageAtOpen == nil {
            languageAtOpen = language
        }
        notificationsOn = config.macosNotifications ?? true
        interval = config.syncIntervalSeconds ?? 60
        bidirectional = config.bidirectional ?? true
        adoptSafety(from: config)
        proxy = ProxyChoice(configValue: config.proxy)
    }

    // MARK: General

    func setStartAtLogin(_ enabled: Bool) async {
        guard let client = app.client, enabled != startAtLogin else {
            return
        }
        if enabled && AppInfo.runsFromTemporaryLocation {
            errorMessage = AppInfo.temporaryLocationMessage
            return
        }
        updatingLoginItem = true
        errorMessage = nil
        do {
            if enabled {
                try await client.installAgent()
            } else {
                // Called from the app, this only removes the login item; the
                // running copy keeps syncing until it quits.
                try await client.uninstallAgent()
            }
            startAtLogin = enabled
        } catch {
            show(error)
        }
        updatingLoginItem = false
        app.scheduleStatusRefresh()
    }

    func setLanguage(_ value: String) async {
        guard value != language else {
            return
        }
        if await merge(["language": .string(value)]) {
            LanguagePreference.apply(value)
        }
    }

    /// True after the language was changed in this window; it applies on restart.
    var languageNeedsRestart: Bool {
        guard let languageAtOpen else {
            return false
        }
        return language != languageAtOpen
    }

    func restartApp() {
        Relauncher.restart(showingSettings: true)
    }

    func setNotifications(_ enabled: Bool) async {
        guard enabled != notificationsOn else {
            return
        }
        if await merge(["macos_notifications": .bool(enabled)]), enabled {
            await app.notifier.requestAuthorization()
        }
        await refreshNotificationPermission()
    }

    func openNotificationSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.notifications") {
            NSWorkspace.shared.open(url)
        }
    }

    private func refreshNotificationPermission() async {
        notificationsDenied = await app.notifier.authorizationStatus() == .denied
    }

    func setInterval(_ seconds: Int) async {
        guard seconds != interval else {
            return
        }
        _ = await merge(["sync_interval_seconds": .int(seconds)])
    }

    // MARK: Drafts

    var listsChanged: Bool {
        Set(lists.selectedTitles) != Set(saved.includeLists ?? []) || bidirectional != (saved.bidirectional ?? true)
    }

    func saveLists() async {
        _ = await merge([
            "include_lists": .strings(lists.selectedTitles),
            "bidirectional": .bool(bidirectional),
        ])
    }

    func revertLists() {
        lists.selected = Set(saved.includeLists ?? [])
        bidirectional = saved.bidirectional ?? true
    }

    var safetyChanged: Bool {
        deleteStale != (saved.deleteStale ?? true)
            || maxChanges != (saved.maxDestructiveChanges ?? 25)
            || maxRatioPercent != Int(((saved.maxDestructiveRatio ?? 0.25) * 100).rounded())
            || conflictPolicy != (saved.conflictPolicy ?? "newer_wins")
    }

    func saveSafety() async {
        _ = await merge([
            "delete_stale": .bool(deleteStale),
            "max_destructive_changes": .int(maxChanges),
            "max_destructive_ratio": .double(Double(maxRatioPercent) / 100),
            "conflict_policy": .string(conflictPolicy),
        ])
    }

    func revertSafety() {
        adoptSafety(from: saved)
    }

    private func adoptSafety(from config: BridgeConfig) {
        deleteStale = config.deleteStale ?? true
        maxChanges = config.maxDestructiveChanges ?? 25
        maxRatioPercent = Int(((config.maxDestructiveRatio ?? 0.25) * 100).rounded())
        conflictPolicy = config.conflictPolicy ?? "newer_wins"
    }

    var networkChanged: Bool {
        proxy.configValue != (saved.proxy ?? "")
    }

    func saveNetwork() async {
        guard proxy.isValid else {
            return
        }
        _ = await merge(["proxy": .string(proxy.configValue)])
    }

    func revertNetwork() {
        proxy = ProxyChoice(configValue: saved.proxy)
    }

    // MARK: Google

    func checkAccount() async {
        guard let client = app.client else {
            return
        }
        checkingAccount = true
        accountProblem = nil
        do {
            let account = try await client.account()
            accountEmail = account.accountEmail
        } catch {
            accountEmail = nil
            accountProblem = (error as? EngineError)?.message ?? error.localizedDescription
        }
        checkingAccount = false
    }

    func reconnect() {
        guard let client = app.client else {
            return
        }
        signInTask?.cancel()
        signingIn = true
        accountProblem = nil
        signInTask = Task {
            do {
                let result = try await client.signIn()
                accountEmail = result.accountEmail
                needsReconnect = false
                app.scheduleStatusRefresh()
            } catch let error as EngineError where error.isCancellation {
                // Cancelled by the person; nothing to report.
            } catch {
                accountProblem = (error as? EngineError)?.message ?? error.localizedDescription
            }
            signingIn = false
        }
    }

    func cancelSignIn() {
        signInTask?.cancel()
    }

    func signOut() async {
        guard let client = app.client else {
            return
        }
        let confirmed = Alerts.confirm(
            title: NSLocalizedString("Sign out of Google?", comment: "Alert title"),
            message: NSLocalizedString("Syncing stops until you sign in again, and Google is asked to revoke access for Local Tasks Bridge. Your sync history stays on this Mac, so signing in to the same account later continues where you left off.", comment: "Alert message"),
            confirmTitle: NSLocalizedString("Sign Out", comment: "Button"),
            destructive: true
        )
        guard confirmed else {
            return
        }
        do {
            try await client.signOut(revoke: true)
            accountEmail = nil
            accountProblem = nil
        } catch {
            show(error)
        }
        app.scheduleStatusRefresh()
    }

    func chooseSharedClient(_ shared: Bool) async {
        if await merge(["oauth_client": .string(shared ? "bundled" : "custom")]) {
            clientStatus = try? await app.client?.clientStatus()
            needsReconnect = true
        }
    }

    func importClient() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = NSLocalizedString("Choose the OAuth client JSON file you downloaded from Google Cloud.", comment: "Open panel message")
        panel.prompt = NSLocalizedString("Import", comment: "Open panel button")
        guard panel.runModal() == .OK, let file = panel.url, let client = app.client else {
            return
        }
        Task {
            do {
                importedClientHint = try await client.importClient(at: file).clientIdHint
                clientStatus = try? await client.clientStatus()
                needsReconnect = true
                saved = try await client.configShow()
            } catch {
                show(error)
            }
        }
    }

    func resetSettings() async {
        do {
            if try await app.resetSettings() {
                errorMessage = nil
                await load()
            }
        } catch {
            show(error)
        }
    }

    // MARK: Advanced

    func installCommandLineTool() {
        do {
            try CommandLineTool.install(at: app.paths.commandLineToolLink)
            commandLineToolInstalled = true
            commandLineToolMessage = NSLocalizedString("Installed. Open Terminal and run “ltb status”. If the command is not found, add ~/.local/bin to your PATH.", comment: "Command-line tool installed")
        } catch {
            commandLineToolMessage = error.localizedDescription
        }
    }

    // MARK: Helpers

    /// Saves through the app model, which also refreshes the running loop.
    /// Only the drafts that were saved are refreshed; other unsaved edits stay.
    private func merge(_ values: [String: JSONValue]) async -> Bool {
        saving = true
        errorMessage = nil
        defer { saving = false }
        let updated: BridgeConfig
        do {
            updated = try await app.mergeConfig(values)
        } catch {
            show(error)
            return false
        }
        saved = updated
        language = updated.language ?? "auto"
        notificationsOn = updated.macosNotifications ?? true
        interval = updated.syncIntervalSeconds ?? 60
        let keys = Set(values.keys)
        if keys.contains("bidirectional") {
            bidirectional = updated.bidirectional ?? true
        }
        if keys.contains("include_lists") {
            lists.selected = Set(updated.includeLists ?? [])
        }
        if !keys.isDisjoint(with: ["delete_stale", "max_destructive_changes", "max_destructive_ratio", "conflict_policy"]) {
            adoptSafety(from: updated)
        }
        if keys.contains("proxy") {
            proxy = ProxyChoice(configValue: updated.proxy)
        }
        return true
    }

    private func show(_ error: Error) {
        if let engineError = error as? EngineError {
            if !engineError.isCancellation {
                errorMessage = engineError.message
            }
        } else {
            errorMessage = error.localizedDescription
        }
    }

    func cancelWork() {
        signInTask?.cancel()
        rebuildModel?.cancelWork()
    }
}
