import AppKit
import UniformTypeIdentifiers

/// State and actions of the Setup Assistant window.
@MainActor
final class SetupModel: ObservableObject {
    enum Step: Int, CaseIterable {
        case welcome, reminders, signInMethod, signIn, lists, options, firstSync, done

        var shortTitle: String {
            switch self {
            case .welcome: return NSLocalizedString("Welcome", comment: "Setup step")
            case .reminders: return NSLocalizedString("Reminders", comment: "Setup step")
            case .signInMethod: return NSLocalizedString("Method", comment: "Setup step")
            case .signIn: return NSLocalizedString("Sign In", comment: "Setup step")
            case .lists: return NSLocalizedString("Lists", comment: "Setup step")
            case .options: return NSLocalizedString("Options", comment: "Setup step")
            case .firstSync: return NSLocalizedString("First Sync", comment: "Setup step")
            case .done: return NSLocalizedString("Done", comment: "Setup step")
            }
        }
    }

    enum SignInMethod {
        case shared
        case own
    }

    let app: AppModel
    let lists: ListSelectionModel
    /// Closes the window; set by the window coordinator.
    var close: () -> Void = {}

    @Published private(set) var step: Step = .welcome
    @Published private(set) var working = false
    @Published private(set) var workingMessage: String?
    /// Whether the running action may be cancelled (sign-in and read-only checks).
    @Published private(set) var workCancellable = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var errorCode: String?

    @Published private(set) var remindersAccess: RemindersAuthorization
    @Published private(set) var clientStatus: OAuthClientStatus?
    @Published var method: SignInMethod = .shared
    @Published private(set) var importedClientHint: String?
    @Published private(set) var accountEmail: String?
    @Published var options = SyncOptions()
    @Published var showsProxySettings = false
    @Published private(set) var plan: SyncPlan?
    @Published private(set) var loginItemProblem: String?
    @Published private(set) var commandLineToolMessage: String?
    @Published private(set) var commandLineToolInstalled = false

    private var task: Task<Void, Never>?
    private var taskToken = UUID()
    private var retry: (() -> Void)?
    private var importedExistingSetup = false
    private var methodChosen = false
    private var methodAtSignIn: SignInMethod?
    private var optionsPrepared = false
    private var proxyLoaded = false

    init(app: AppModel) {
        self.app = app
        self.lists = ListSelectionModel(app: app)
        self.remindersAccess = app.reminders.authorization
        self.commandLineToolInstalled = CommandLineTool.isInstalled(at: app.paths.commandLineToolLink)
    }

    // MARK: Navigation

    var canGoBack: Bool {
        !working && step != .welcome && step != .done
    }

    var canContinue: Bool {
        guard !working else {
            return false
        }
        switch step {
        case .welcome:
            return app.client != nil
        case .reminders:
            return remindersAccess == .granted
        case .signInMethod:
            guard options.proxy.isValid else {
                return false
            }
            switch method {
            case .shared: return clientStatus?.bundledAvailable == true
            case .own: return clientStatus?.customReady == true
            }
        case .signIn:
            return accountEmail != nil
        case .lists:
            return !lists.loading && !lists.selected.isEmpty
        case .options:
            return options.proxy.isValid
        case .firstSync:
            return false
        case .done:
            return true
        }
    }

    var usesSharedClient: Bool {
        method == .shared && clientStatus?.bundledAvailable == true
    }

    func goBack() {
        guard canGoBack, let previous = Step(rawValue: step.rawValue - 1) else {
            return
        }
        show(previous)
    }

    func continueForward() {
        guard canContinue else {
            return
        }
        switch step {
        case .welcome:
            run { await self.leaveWelcome() }
        case .reminders:
            if importedExistingSetup {
                run(NSLocalizedString("Finishing setup…", comment: "Setup progress")) { await self.finish() }
            } else {
                show(.signInMethod)
            }
        case .signInMethod:
            run { await self.saveSignInMethod() }
        case .signIn:
            show(.lists)
        case .lists:
            show(.options)
        case .options:
            run { await self.saveOptions() }
        case .firstSync:
            break
        case .done:
            close()
        }
    }

    /// Stops the current action if it may be stopped; write commands always finish.
    func cancelWork() {
        if workCancellable {
            task?.cancel()
        }
    }

    func retryLastAction() {
        retry?()
    }

    func jump(to target: Step) {
        if target == .signIn {
            accountEmail = nil
        }
        show(target)
    }

    private func show(_ next: Step) {
        step = next
        clearError()
        switch next {
        case .reminders:
            remindersAccess = app.reminders.authorization
        case .signInMethod:
            // The proxy is chosen here too, so people behind one can sign in.
            if !proxyLoaded, let config = app.config {
                options.proxy = ProxyChoice(configValue: config.proxy)
                showsProxySettings = options.proxy.mode != .system
                proxyLoaded = true
            }
            run(cancellable: true) { await self.loadClientStatus() }
        case .signIn:
            if accountEmail == nil {
                run(NSLocalizedString("Checking your Google sign-in…", comment: "Setup progress"), cancellable: true) { await self.checkExistingSignIn() }
            }
        case .lists:
            if !lists.loaded {
                Task { await self.loadLists() }
            }
        case .options:
            prepareOptions()
        case .firstSync:
            run(NSLocalizedString("Checking what the first sync will do…", comment: "Setup progress"), cancellable: true) { await self.previewFirstSync() }
        case .welcome, .done:
            break
        }
    }

    // MARK: Welcome

    var legacyInstallDetected: Bool {
        app.status?.legacyInstallDetected == true
    }

    private func leaveWelcome() async {
        guard let client = app.client else {
            return
        }
        do {
            let status = try await app.currentStatus()
            if status.configExists != true {
                try await client.configInit()
            }
            await app.reloadConfig()
            show(.reminders)
        } catch {
            present(error) { self.run { await self.leaveWelcome() } }
        }
    }

    func importExistingSetup() {
        guard !AppInfo.runsFromTemporaryLocation else {
            errorMessage = AppInfo.temporaryLocationMessage
            return
        }
        run(NSLocalizedString("Importing your earlier setup…", comment: "Setup progress")) {
            await self.performImport()
        }
    }

    private func performImport() async {
        guard let client = app.client else {
            return
        }
        do {
            _ = try await client.migrate()
            importedExistingSetup = true
            await app.reloadConfig()
            if app.reminders.authorization == .notDetermined {
                NSApp.activate(ignoringOtherApps: true)
                _ = try? await app.reminders.requestAccess()
            }
            remindersAccess = app.reminders.authorization
            if remindersAccess == .granted {
                await finish()
            } else {
                show(.reminders)
            }
        } catch {
            present(error) { self.importExistingSetup() }
        }
    }

    func installAppleCommandLineTools() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/xcode-select")
        process.arguments = ["--install"]
        try? process.run()
    }

    func checkPythonAgain() {
        run(NSLocalizedString("Looking for Python…", comment: "Setup progress"), cancellable: true) {
            await self.app.locateEngine()
            await self.app.reloadConfig()
            await self.app.refreshStatus()
        }
    }

    // MARK: Reminders

    func requestRemindersAccess() {
        run {
            NSApp.activate(ignoringOtherApps: true)
            do {
                _ = try await self.app.reminders.requestAccess()
            } catch {
                self.errorMessage = error.localizedDescription
            }
            self.remindersAccess = self.app.reminders.authorization
        }
    }

    func refreshRemindersAccess() {
        remindersAccess = app.reminders.authorization
    }

    func openRemindersPrivacySettings() {
        NSWorkspace.shared.open(RemindersAccess.privacySettingsURL)
    }

    // MARK: Sign-in method

    private func loadClientStatus() async {
        guard let client = app.client else {
            return
        }
        do {
            let status = try await client.clientStatus()
            clientStatus = status
            if !methodChosen {
                let ownClientPreferred = status.mode == "custom" && status.customReady == true
                method = status.bundledAvailable == true && !ownClientPreferred ? .shared : .own
            }
            if status.bundledAvailable != true {
                method = .own
            }
        } catch {
            present(error) { self.run(cancellable: true) { await self.loadClientStatus() } }
        }
    }

    func choose(_ newMethod: SignInMethod) {
        method = newMethod
        methodChosen = true
    }

    func chooseClientFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = NSLocalizedString("Choose the OAuth client JSON file you downloaded from Google Cloud.", comment: "Open panel message")
        panel.prompt = NSLocalizedString("Import", comment: "Open panel button")
        NSApp.activate(ignoringOtherApps: true)
        guard panel.runModal() == .OK, let file = panel.url else {
            return
        }
        run(NSLocalizedString("Importing the OAuth client…", comment: "Setup progress")) {
            guard let client = self.app.client else {
                return
            }
            do {
                let result = try await client.importClient(at: file)
                self.importedClientHint = result.clientIdHint
                self.choose(.own)
                await self.loadClientStatus()
            } catch {
                self.present(error)
            }
        }
    }

    private func saveSignInMethod() async {
        do {
            try await app.mergeConfig([
                "oauth_client": .string(method == .shared ? "bundled" : "custom"),
                "proxy": .string(options.proxy.configValue),
            ])
            if let methodAtSignIn, methodAtSignIn != method {
                accountEmail = nil
            }
            show(.signIn)
        } catch {
            present(error) { self.run { await self.saveSignInMethod() } }
        }
    }

    // MARK: Sign in

    func signIn() {
        run(NSLocalizedString("Waiting for you to finish signing in in your browser…", comment: "Setup progress"), cancellable: true) {
            guard let client = self.app.client else {
                return
            }
            do {
                let result = try await client.signIn()
                self.accountEmail = result.accountEmail ?? ""
                self.methodAtSignIn = self.method
                self.app.scheduleStatusRefresh()
            } catch {
                self.present(error) { self.signIn() }
            }
        }
    }

    private func checkExistingSignIn() async {
        guard let client = app.client, (try? await app.currentStatus())?.tokenReady == true else {
            return
        }
        if let account = try? await client.account(), let email = account.accountEmail, !email.isEmpty {
            accountEmail = email
            methodAtSignIn = method
        }
    }

    // MARK: Lists

    func loadLists() async {
        let configured = app.config?.includeLists ?? []
        await lists.load(preselect: configured.isEmpty ? nil : configured)
        guard lists.selected.isEmpty, lists.errorMessage == nil else {
            return
        }
        let matching = lists.rows.filter { $0.match == .google }.map(\.title)
        if !matching.isEmpty {
            lists.selected = Set(matching)
        } else if let fallback = app.reminders.defaultListTitle, lists.rows.contains(where: { $0.title == fallback }) {
            lists.selected = [fallback]
        }
    }

    // MARK: Options

    private func prepareOptions() {
        guard !optionsPrepared, let config = app.config else {
            return
        }
        options = SyncOptions(config: config, sharedClient: usesSharedClient)
        optionsPrepared = true
    }

    var safetyLimitDescription: String {
        let changes = app.config?.maxDestructiveChanges ?? 25
        let percent = Int(((app.config?.maxDestructiveRatio ?? 0.25) * 100).rounded())
        return String(
            format: NSLocalizedString("When you complete or delete an item on one side, the same happens on the other. For safety, if one sync would complete or delete more than %d items or %d%% of your synced items, those changes wait for your approval while everything else keeps syncing.", comment: "Setup options; first %d is a count, second is a percentage"),
            changes, percent
        )
    }

    private func saveOptions() async {
        var values = options.mergeValues
        values["include_lists"] = .strings(lists.selectedTitles)
        do {
            try await app.mergeConfig(values)
            show(.firstSync)
        } catch {
            present(error) { self.run { await self.saveOptions() } }
        }
    }

    // MARK: First sync

    var planSummary: PlanSummary { PlanSummary(plan: plan) }

    private func previewFirstSync() async {
        plan = nil
        guard let client = app.client else {
            return
        }
        do {
            plan = try await client.sync(dryRun: true, deleteStale: false).plan ?? SyncPlan()
        } catch {
            present(error) { self.show(.firstSync) }
        }
    }

    func startSyncing() {
        run(NSLocalizedString("Syncing… This can take a minute.", comment: "Setup progress")) {
            guard let client = self.app.client else {
                return
            }
            do {
                _ = try await client.sync(dryRun: false, deleteStale: false)
                await self.finish()
            } catch {
                self.present(error) { self.startSyncing() }
            }
        }
    }

    private func finish() async {
        do {
            loginItemProblem = try await app.completeSetup()?.message
            show(.done)
        } catch {
            present(error) { self.run { await self.finish() } }
        }
    }

    // MARK: Done

    var intervalDescription: String {
        IntervalPicker.label(
            for: app.status?.effectiveSyncIntervalSeconds ?? app.config?.syncIntervalSeconds ?? options.intervalSeconds
        )
    }

    func installCommandLineTool() {
        do {
            try CommandLineTool.install(at: app.paths.commandLineToolLink)
            commandLineToolInstalled = true
            commandLineToolMessage = NSLocalizedString("Installed. Open Terminal and run “ltb status”. If the command is not found, add ~/.local/bin to your PATH.", comment: "Command-line tool installed")
        } catch {
            commandLineToolMessage = error.localizedDescription
        }
    }

    /// Resets an unreadable config.json (see `AppModel.resetSettings`).
    func resetSettings() {
        run {
            do {
                if try await self.app.resetSettings() {
                    self.show(self.step)
                }
            } catch {
                self.present(error)
            }
        }
    }

    // MARK: Helpers

    /// Runs one step action at a time; `working` stays true until it ends.
    /// Only sign-in and read-only actions are `cancellable`.
    private func run(_ message: String? = nil, cancellable: Bool = false, _ work: @escaping () async -> Void) {
        task?.cancel()
        let token = UUID()
        taskToken = token
        working = true
        workCancellable = cancellable
        workingMessage = message
        clearError()
        task = Task { [weak self] in
            await work()
            guard let self, self.taskToken == token else {
                return
            }
            self.working = false
            self.workingMessage = nil
        }
    }

    private func present(_ error: Error, retry: (() -> Void)? = nil) {
        if let engineError = error as? EngineError {
            if engineError.isCancellation {
                return
            }
            errorCode = engineError.code
            errorMessage = engineError.message
        } else {
            errorCode = nil
            errorMessage = error.localizedDescription
        }
        self.retry = retry
    }

    private func clearError() {
        errorMessage = nil
        errorCode = nil
        retry = nil
    }

    var canRetry: Bool { retry != nil }
}
