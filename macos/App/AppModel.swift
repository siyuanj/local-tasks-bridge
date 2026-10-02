import AppKit
import Combine

/// The app's shared state: which engine to run, the latest `status --json`,
/// the supervised `run-loop`, and the triggers that keep the status fresh.
@MainActor
final class AppModel: ObservableObject {
    static let statusPollInterval: TimeInterval = 30
    static let localChangeDebounce: TimeInterval = 5
    /// Reminders changes this soon after a cycle are most likely the engine's own writes.
    static let ownWriteQuietPeriod: TimeInterval = 10

    let paths: AppPaths
    let log: AppLog
    let reminders = RemindersAccess()
    let notifier = Notifier()
    let supervisor: EngineSupervisor

    @Published private(set) var availability: EngineAvailability = .locating
    @Published private(set) var status: EngineStatus?
    @Published private(set) var statusError: EngineError?
    @Published private(set) var config: BridgeConfig?
    @Published private(set) var cycleInProgress = false
    @Published private(set) var supervisorPhase: EngineSupervisor.Phase = .stopped
    /// Set while Quit waits for write commands and the loop to finish.
    @Published private(set) var quitting = false

    private(set) var client: EngineClient?
    /// While set (during uninstall), the loop is not restarted.
    private var backgroundWorkSuspended = false
    private var refreshInFlight = false
    private var refreshAgain = false
    private var pollTimer: Timer?
    private var pendingStatusRefresh: DispatchWorkItem?
    private var pendingLocalSync: DispatchWorkItem?
    private var lastCycleFinishedAt: Date?
    /// A Reminders change arrived during a cycle; sync again once it is over.
    private var deferredLocalChange = false

    /// Set by the app delegate: opens Review Pending Changes.
    var showApprovals: (() -> Void)?

    init(paths: AppPaths, log: AppLog) {
        self.paths = paths
        self.log = log
        self.supervisor = EngineSupervisor(log: log)
        supervisor.onEvent = { [weak self] event in
            self?.handle(event)
        }
        supervisor.onPhaseChange = { [weak self] phase in
            self?.supervisorPhase = phase
            if phase != .running {
                self?.cycleInProgress = false
            }
        }
        notifier.onOpen = { [weak self] kind in
            guard let self, kind == .approval || self.needsApproval else {
                return
            }
            self.showApprovals?()
        }
    }

    // MARK: Derived state

    var needsSetup: Bool {
        switch availability {
        case .pythonMissing, .engineMissing:
            return true
        case .locating:
            return false
        case .ready:
            return !(status?.isSetupCompleted ?? false)
        }
    }

    var needsApproval: Bool {
        guard let condition = status?.condition else {
            return false
        }
        return condition == "mutation_approval_pending" || condition == "mutation_blocked"
    }

    /// The engine asks people to choose "Reconnect Google…" in these states.
    var needsGoogleSignIn: Bool {
        guard status?.isSetupCompleted == true, let condition = status?.condition else {
            return false
        }
        return condition == "auth_required" || condition == "account_binding_required"
    }

    /// `status` could not read config.json; only resetting it helps.
    var configUnreadable: Bool {
        statusError?.code == EngineErrorCode.configInvalid
    }

    var canSyncNow: Bool {
        client != nil && status?.isSetupCompleted == true && status?.isPaused == false
    }

    var usesSharedClient: Bool {
        status?.oauthClient?.usesSharedClient ?? false
    }

    // MARK: Startup and shutdown

    func start() async {
        notifier.activate()
        await locateEngine()
        await reloadConfig()
        await refreshStatus()
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: Self.statusPollInterval, repeats: true) { [weak self] _ in
            Task { await self?.refreshStatus() }
        }
    }

    func locateEngine() async {
        availability = .locating
        let bundle = AppInfo.bundleURL
        let found = await Task.detached(priority: .userInitiated) {
            PythonLocator.locate(bundle: bundle)
        }.value
        availability = found
        switch found {
        case .ready(let runtime):
            client = EngineClient(runtime: runtime, paths: paths, log: log)
            log.write("engine \(runtime.engine.path) with Python \(runtime.python.path)")
        case .pythonMissing:
            client = nil
            log.write("no usable Python 3.9+ found")
        case .engineMissing(let path):
            client = nil
            log.write("engine script missing at \(path)")
        case .locating:
            client = nil
        }
    }

    /// Stops read-only commands, waits for write commands (they are never
    /// interrupted), then stops the loop, which finishes a cycle in progress.
    func prepareToQuit() async {
        quitting = true
        pollTimer?.invalidate()
        pendingLocalSync?.cancel()
        client?.terminateReadOnlyCommands()
        await client?.waitForWrites()
        await supervisor.stop()
        log.write("Local Tasks Bridge quit")
        log.flush()
    }

    // MARK: Status

    func refreshStatus() async {
        guard let client else {
            status = nil
            return
        }
        if refreshInFlight {
            refreshAgain = true
            return
        }
        refreshInFlight = true
        repeat {
            refreshAgain = false
            do {
                status = try await client.status()
                statusError = nil
            } catch let error as EngineError {
                statusError = error
            } catch {
                statusError = EngineError(code: EngineErrorCode.failed, message: error.localizedDescription)
            }
        } while refreshAgain
        refreshInFlight = false
        updateSupervisor()
    }

    /// Fetches the status now, for callers that need it to be current.
    func currentStatus() async throws -> EngineStatus {
        guard let client else {
            throw EngineError(code: EngineErrorCode.engineUnavailable)
        }
        let latest = try await client.status()
        status = latest
        statusError = nil
        updateSupervisor()
        return latest
    }

    func scheduleStatusRefresh(after delay: TimeInterval = 0.5) {
        pendingStatusRefresh?.cancel()
        let work = DispatchWorkItem { [weak self] in
            Task { await self?.refreshStatus() }
        }
        pendingStatusRefresh = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    func reloadConfig() async {
        guard let client else {
            return
        }
        if let loaded = try? await client.configShow() {
            config = loaded
            LanguagePreference.apply(loaded.language)
        }
    }

    /// Stops the loop and keeps it stopped until `resumeBackgroundWork()`.
    func suspendBackgroundWork() async {
        backgroundWorkSuspended = true
        pendingLocalSync?.cancel()
        await supervisor.stop()
    }

    func resumeBackgroundWork() async {
        backgroundWorkSuspended = false
        await refreshStatus()
    }

    private func updateSupervisor() {
        guard !backgroundWorkSuspended, let client, let status else {
            return
        }
        if status.isSetupCompleted {
            if !supervisor.isActive {
                supervisor.start(with: client)
            }
            startObservingReminders()
        } else if supervisor.isActive {
            Task { await supervisor.stop() }
        }
    }

    // MARK: Actions

    /// Saves settings with `config merge`. Keys that change what the loop does
    /// restart it (once it is idle) so the next cycle uses them right away.
    @discardableResult
    func mergeConfig(_ values: [String: JSONValue]) async throws -> BridgeConfig {
        guard let client else {
            throw EngineError(code: EngineErrorCode.engineUnavailable)
        }
        let updated = try await client.configMerge(values)
        config = updated
        if supervisor.isActive && ConfigKeys.affectRunningLoop(Set(values.keys)) {
            supervisor.restart()
        }
        scheduleStatusRefresh()
        return updated
    }

    func syncNow() async throws {
        guard let client else {
            throw EngineError(code: EngineErrorCode.engineUnavailable)
        }
        try await client.syncNow()
        scheduleStatusRefresh()
    }

    func setPaused(_ paused: Bool) async throws {
        guard let client else {
            throw EngineError(code: EngineErrorCode.engineUnavailable)
        }
        if paused {
            try await client.pause()
        } else {
            try await client.resume()
        }
        await refreshStatus()
    }

    /// Runs after the first sync (or an import): marks setup complete, turns on
    /// the login item, and starts background syncing. Returns a problem with
    /// the login item, which does not stop syncing while the app runs.
    func completeSetup() async throws -> EngineError? {
        guard let client else {
            throw EngineError(code: EngineErrorCode.engineUnavailable)
        }
        // A login item pointing into App Translocation would break after restart.
        guard !AppInfo.runsFromTemporaryLocation else {
            throw EngineError(code: EngineErrorCode.failed, message: AppInfo.temporaryLocationMessage)
        }
        config = try await client.configMerge(["setup_completed_at": .string(EngineDate.string(from: Date()))])
        var loginItemProblem: EngineError?
        do {
            try await client.installAgent()
        } catch let error as EngineError {
            loginItemProblem = error
        }
        _ = try? await currentStatus()
        supervisor.start(with: client)
        await notifier.requestAuthorization()
        return loginItemProblem
    }

    /// Replaces an unreadable config.json with the defaults (`config init
    /// --force` backs the old file up first), after asking. Returns false if
    /// the person cancelled.
    @discardableResult
    func resetSettings() async throws -> Bool {
        guard let client else {
            throw EngineError(code: EngineErrorCode.engineUnavailable)
        }
        let confirmed = Alerts.confirm(
            title: NSLocalizedString("Reset settings?", comment: "Alert title"),
            message: NSLocalizedString("The settings file is copied to the backups folder and replaced with the default settings. Your Google sign-in and sync history stay as they are.", comment: "Alert message"),
            confirmTitle: NSLocalizedString("Reset Settings", comment: "Button")
        )
        guard confirmed else {
            return false
        }
        try await client.configInit(force: true)
        await reloadConfig()
        await refreshStatus()
        return true
    }

    // MARK: Engine events

    private func handle(_ event: EngineEvent) {
        switch event.event {
        case "cycle_started":
            cycleInProgress = true
        case "cycle_finished":
            cycleInProgress = false
            lastCycleFinishedAt = Date()
            if deferredLocalChange {
                scheduleLocalSync(after: Self.ownWriteQuietPeriod)
            }
        case "notification":
            if config?.macosNotifications ?? true {
                notifier.post(
                    title: event.title ?? AppInfo.productName,
                    message: event.message ?? "",
                    kind: event.severity == "problem" ? .problem : .info
                )
            }
        case "approval_requested":
            // Under the app the engine shows no dialog of its own; the review
            // window is the prompt, and the notification brings it back later.
            if config?.macosNotifications ?? true {
                notifier.post(
                    title: NSLocalizedString("Review Pending Changes", comment: "Window title"),
                    message: NSLocalizedString("A large batch of deletions or completions is waiting for your approval. Everything else keeps syncing.", comment: "Notification message"),
                    kind: .approval
                )
            }
            showApprovals?()
        default:
            break
        }
        scheduleStatusRefresh()
    }

    // MARK: Local changes

    private func startObservingReminders() {
        guard reminders.authorization == .granted else {
            return
        }
        reminders.observeChanges { [weak self] in
            self?.remindersDidChange()
        }
    }

    /// Debounces local changes into one `sync-now`. Changes during a cycle, or
    /// just after one (often the engine's own writes), are deferred until the
    /// cycle has ended and the quiet period has passed; they are never dropped.
    private func remindersDidChange() {
        guard canSyncNow else {
            return
        }
        if cycleInProgress {
            deferredLocalChange = true
            return
        }
        let quietLeft = lastCycleFinishedAt.map { Self.ownWriteQuietPeriod - Date().timeIntervalSince($0) } ?? 0
        scheduleLocalSync(after: max(Self.localChangeDebounce, quietLeft))
    }

    private func scheduleLocalSync(after delay: TimeInterval) {
        pendingLocalSync?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.canSyncNow else {
                return
            }
            if self.cycleInProgress {
                self.deferredLocalChange = true
                return
            }
            self.deferredLocalChange = false
            Task { try? await self.client?.syncNow() }
        }
        pendingLocalSync = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }
}

/// Applies the app language chosen in Settings (or with `ltb config merge`)
/// on the next launch, by overriding AppleLanguages for this app only.
enum LanguagePreference {
    static func localization(for language: String?) -> String? {
        switch language {
        case "zh": return "zh-Hans"
        case "en": return "en"
        default: return nil
        }
    }

    static func apply(_ language: String?) {
        let defaults = UserDefaults.standard
        let current = defaults.persistentDomain(forName: AppInfo.bundleIdentifier)?["AppleLanguages"] as? [String]
        let desired = localization(for: language).map { [$0] }
        guard current != desired else {
            return
        }
        if let desired {
            defaults.set(desired, forKey: "AppleLanguages")
        } else {
            defaults.removeObject(forKey: "AppleLanguages")
        }
    }
}
