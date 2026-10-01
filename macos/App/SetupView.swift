import SwiftUI

/// The Setup Assistant window: step indicator, the current step, Back/Continue.
struct SetupView: View {
    @ObservedObject var model: SetupModel
    @ObservedObject var app: AppModel

    init(model: SetupModel) {
        self.model = model
        self.app = model.app
    }

    var body: some View {
        VStack(spacing: 0) {
            StepIndicator(titles: SetupModel.Step.allCases.map(\.shortTitle), current: model.step.rawValue)
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    stepContent
                    if let message = model.errorMessage {
                        SetupErrorView(model: model, message: message)
                    }
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Divider()
            footer
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
        }
        .frame(width: 680, height: 580)
    }

    @ViewBuilder
    private var stepContent: some View {
        switch model.step {
        case .welcome: WelcomeStep(model: model, app: app)
        case .reminders: RemindersStep(model: model)
        case .signInMethod: SignInMethodStep(model: model)
        case .signIn: SignInStep(model: model)
        case .lists: ListsStep(model: model)
        case .options: OptionsStep(model: model)
        case .firstSync: FirstSyncStep(model: model)
        case .done: DoneStep(model: model)
        }
    }

    private var footer: some View {
        HStack(spacing: 10) {
            if model.working {
                ProgressView().controlSize(.small)
                if let message = model.workingMessage {
                    Text(message)
                        .foregroundColor(.secondary)
                        .lineLimit(2)
                }
                if model.step == .signIn || model.step == .firstSync {
                    Button(NSLocalizedString("Cancel", comment: "Button")) { model.cancelWork() }
                }
            }
            Spacer()
            if model.step != .welcome && model.step != .done {
                Button(NSLocalizedString("Back", comment: "Button")) { model.goBack() }
                    .disabled(!model.canGoBack)
            }
            if model.step != .firstSync {
                Button(model.step == .done ? NSLocalizedString("Done", comment: "Button") : NSLocalizedString("Continue", comment: "Button")) {
                    model.continueForward()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(!model.canContinue)
            }
        }
    }
}

/// Step title in a consistent style.
private struct StepHeader: View {
    var title: String
    var subtitle: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.title2).bold()
            if let subtitle {
                Text(subtitle)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// The error of the current step with the matching way out.
private struct SetupErrorView: View {
    @ObservedObject var model: SetupModel
    var message: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ErrorText(message: message)
            HStack {
                if let recovery {
                    Button(recovery.title) { model.jump(to: recovery.step) }
                }
                if model.canRetry {
                    Button(NSLocalizedString("Try Again", comment: "Button")) { model.retryLastAction() }
                }
            }
        }
        .padding(12)
        .background(Color.orange.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    /// The step that fixes the problem, when it is not the current one.
    private var recovery: (title: String, step: SetupModel.Step)? {
        let target: (title: String, step: SetupModel.Step)?
        switch model.errorCode ?? "" {
        case EngineErrorCode.authRequired, EngineErrorCode.accountBindingRequired:
            target = (NSLocalizedString("Sign In Again", comment: "Button"), .signIn)
        case EngineErrorCode.remindersUnavailable:
            target = (NSLocalizedString("Check Reminders Access", comment: "Button"), .reminders)
        case EngineErrorCode.oauthClientMissing:
            target = (NSLocalizedString("Choose a Sign-in Method", comment: "Button"), .signInMethod)
        default:
            target = nil
        }
        guard let target, target.step != model.step else {
            return nil
        }
        return target
    }
}

// MARK: - Steps

private struct WelcomeStep: View {
    @ObservedObject var model: SetupModel
    @ObservedObject var app: AppModel

    var body: some View {
        switch app.availability {
        case .pythonMissing:
            pythonRequired
        case .engineMissing:
            StepHeader(
                title: NSLocalizedString("Local Tasks Bridge is incomplete", comment: "Setup title"),
                subtitle: NSLocalizedString("Parts of the app are missing. Download Local Tasks Bridge again and replace this copy.", comment: "Setup text")
            )
        case .locating, .ready:
            welcome
        }
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(
                title: NSLocalizedString("Welcome to Local Tasks Bridge", comment: "Setup title"),
                subtitle: NSLocalizedString("Local Tasks Bridge keeps the Apple Reminders lists you choose in sync with Google Tasks, in both directions.", comment: "Setup text")
            )
            VStack(alignment: .leading, spacing: 8) {
                Text(NSLocalizedString("Private by design", comment: "Setup heading")).font(.headline)
                Label(NSLocalizedString("Runs only on this Mac. There is no Local Tasks Bridge server or account.", comment: "Setup privacy point"), systemImage: "desktopcomputer")
                Label(NSLocalizedString("Your reminders and tasks travel only between this Mac and Google.", comment: "Setup privacy point"), systemImage: "arrow.left.arrow.right")
                Label(NSLocalizedString("Your Google sign-in and sync data stay in a private folder on this Mac.", comment: "Setup privacy point"), systemImage: "lock")
                Link(NSLocalizedString("Privacy Policy", comment: "Link"), destination: AppInfo.privacyPolicyURL)
                    .padding(.top, 2)
            }
            if model.legacyInstallDetected {
                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(NSLocalizedString("An earlier installation was found", comment: "Setup heading")).font(.headline)
                        Text(NSLocalizedString("Import it to keep your list choices, sync history, and Google sign-in. Its old background job is turned off.", comment: "Setup text"))
                            .fixedSize(horizontal: false, vertical: true)
                        Button(NSLocalizedString("Import My Existing Setup", comment: "Button")) { model.importExistingSetup() }
                            .disabled(model.working)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(6)
                }
            }
            if AppInfo.runsFromTemporaryLocation {
                ErrorText(message: NSLocalizedString("Local Tasks Bridge is running from a temporary location. Quit, move it to your Applications folder, and open it again; otherwise it can’t start at login.", comment: "Setup warning"))
            }
        }
    }

    private var pythonRequired: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepHeader(
                title: NSLocalizedString("Python is required", comment: "Setup title"),
                subtitle: NSLocalizedString("Local Tasks Bridge runs its sync engine with Python 3.9 or newer. Install Apple’s Command Line Tools, which include Python, then choose Check Again.", comment: "Setup text")
            )
            HStack {
                Button(NSLocalizedString("Install Command Line Tools…", comment: "Button")) { model.installAppleCommandLineTools() }
                Button(NSLocalizedString("Check Again", comment: "Button")) { model.checkPythonAgain() }
                    .disabled(model.working)
                Link(NSLocalizedString("Learn More", comment: "Link"), destination: AppInfo.helpURL)
            }
        }
    }
}

private struct RemindersStep: View {
    @ObservedObject var model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepHeader(
                title: NSLocalizedString("Allow access to Reminders", comment: "Setup title"),
                subtitle: NSLocalizedString("Local Tasks Bridge needs full access to Reminders. It reads and changes only the lists you choose in a later step.", comment: "Setup text")
            )
            switch model.remindersAccess {
            case .notDetermined:
                Button(NSLocalizedString("Allow Access…", comment: "Button")) { model.requestRemindersAccess() }
                    .disabled(model.working)
            case .granted:
                Label(NSLocalizedString("Access to Reminders is allowed.", comment: "Setup status"), systemImage: "checkmark.circle.fill")
                    .foregroundColor(.green)
            case .denied, .restricted, .writeOnly:
                ErrorText(message: deniedMessage)
                HStack {
                    Button(NSLocalizedString("Open System Settings", comment: "Button")) { model.openRemindersPrivacySettings() }
                    Button(NSLocalizedString("Check Again", comment: "Button")) { model.refreshRemindersAccess() }
                }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            model.refreshRemindersAccess()
        }
    }

    private var deniedMessage: String {
        switch model.remindersAccess {
        case .writeOnly:
            return NSLocalizedString("Local Tasks Bridge can only add reminders. In System Settings > Privacy & Security > Reminders, give it full access, then come back.", comment: "Setup Reminders access")
        case .restricted:
            return NSLocalizedString("Access to Reminders is restricted on this Mac, for example by Screen Time or a management profile.", comment: "Setup Reminders access")
        default:
            return NSLocalizedString("Access to Reminders is turned off. In System Settings > Privacy & Security > Reminders, turn on Local Tasks Bridge, then come back.", comment: "Setup Reminders access")
        }
    }
}

private struct SignInMethodStep: View {
    @ObservedObject var model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepHeader(title: NSLocalizedString("Choose how to sign in to Google", comment: "Setup title"))
            if model.clientStatus?.bundledAvailable == true {
                RadioOption(
                    title: NSLocalizedString("Quick sign-in (recommended)", comment: "Sign-in method"),
                    detail: NSLocalizedString("Uses the shared Local Tasks Bridge sign-in. Google warns that it hasn’t verified this app; you can continue past the warning. Up to 100 people can use the shared sign-in, and they share one daily Google quota.", comment: "Sign-in method detail"),
                    isSelected: model.method == .shared
                ) { model.choose(.shared) }
                RadioOption(
                    title: NSLocalizedString("Use my own Google Cloud OAuth client (advanced, no user limits)", comment: "Sign-in method"),
                    detail: NSLocalizedString("Create a free “Desktop app” OAuth client in Google Cloud and import its JSON file. It has its own quota and no user limit.", comment: "Sign-in method detail"),
                    isSelected: model.method == .own
                ) { model.choose(.own) }
            } else if model.clientStatus != nil {
                Text(NSLocalizedString("This copy of Local Tasks Bridge signs in with your own Google Cloud OAuth client. Creating one is free and takes about 10 minutes.", comment: "Setup text"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if model.method == .own && model.clientStatus != nil {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 12) {
                        Button(NSLocalizedString("Choose Client JSON…", comment: "Button")) { model.chooseClientFile() }
                            .disabled(model.working)
                        Link(NSLocalizedString("Step-by-step guide", comment: "Link"), destination: AppInfo.googleCloudSetupURL)
                    }
                    if let hint = model.importedClientHint {
                        Label(String(format: NSLocalizedString("Imported client %@", comment: "Setup status; %@ is a client ID hint"), hint), systemImage: "checkmark.circle.fill")
                            .foregroundColor(.green)
                    } else if model.clientStatus?.customReady == true {
                        Label(NSLocalizedString("Your own OAuth client is already imported.", comment: "Setup status"), systemImage: "checkmark.circle.fill")
                            .foregroundColor(.green)
                    }
                }
                .padding(.leading, model.clientStatus?.bundledAvailable == true ? 24 : 0)
            }
        }
    }
}

private struct SignInStep: View {
    @ObservedObject var model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepHeader(
                title: NSLocalizedString("Sign in to Google", comment: "Setup title"),
                subtitle: NSLocalizedString("Your browser opens Google’s sign-in page. Choose your account, keep the Google Tasks permission ticked, and come back here when Google says you can close the page.", comment: "Setup text")
            )
            if model.usesSharedClient {
                NoticeText(message: NSLocalizedString("Google will warn that it hasn’t verified this app. Choose “Advanced”, then “Go to Local Tasks Bridge” to continue.", comment: "Setup note"))
            }
            if let email = model.accountEmail {
                Label(
                    email.isEmpty
                        ? NSLocalizedString("Signed in to Google.", comment: "Setup status")
                        : String(format: NSLocalizedString("Signed in as %@", comment: "Setup status; %@ is an email address"), email),
                    systemImage: "checkmark.circle.fill"
                )
                .foregroundColor(.green)
                Button(NSLocalizedString("Use a Different Account", comment: "Button")) { model.signIn() }
                    .disabled(model.working)
            } else {
                Button(NSLocalizedString("Sign In with Google", comment: "Button")) { model.signIn() }
                    .controlSize(.large)
                    .disabled(model.working)
            }
        }
    }
}

private struct ListsStep: View {
    @ObservedObject var model: SetupModel
    @ObservedObject var lists: ListSelectionModel

    init(model: SetupModel) {
        self.model = model
        self.lists = model.lists
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            StepHeader(
                title: NSLocalizedString("Choose the lists to sync", comment: "Setup title"),
                subtitle: NSLocalizedString("Each list you choose syncs with the Google Tasks list of the same name. Missing Google lists are created for you.", comment: "Setup text")
            )
            ListPickerView(model: lists) {
                Task { await model.loadLists() }
            }
            HStack {
                Button(NSLocalizedString("Reload Lists", comment: "Button")) {
                    Task { await model.loadLists() }
                }
                .disabled(lists.loading)
                Spacer()
                if lists.loaded && lists.selected.isEmpty {
                    Text(NSLocalizedString("Choose at least one list.", comment: "Setup validation"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
        }
    }
}

private struct OptionsStep: View {
    @ObservedObject var model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(title: NSLocalizedString("Choose how to sync", comment: "Setup title"))
            DirectionPicker(bidirectional: $model.options.bidirectional)
            Divider()
            VStack(alignment: .leading, spacing: 4) {
                Toggle(NSLocalizedString("Sync completions and deletions", comment: "Option"), isOn: $model.options.deleteStale)
                Text(model.safetyLimitDescription)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.leading, 20)
            }
            Toggle(NSLocalizedString("Include reminders without a due date", comment: "Option"), isOn: $model.options.includeUndated)
            VStack(alignment: .leading, spacing: 4) {
                Toggle(NSLocalizedString("Import existing Google tasks", comment: "Option"), isOn: $model.options.importExisting)
                Text(NSLocalizedString("Tasks already in the matching Google Tasks lists are added to Reminders.", comment: "Option detail"))
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .padding(.leading, 20)
            }
            Divider()
            IntervalPicker(seconds: $model.options.intervalSeconds, sharedClient: model.usesSharedClient)
            Divider()
            Text(NSLocalizedString("Network", comment: "Settings section")).font(.headline)
            ProxyEditor(choice: $model.options.proxy)
        }
        .toggleStyle(.checkbox)
    }
}

private struct FirstSyncStep: View {
    @ObservedObject var model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepHeader(
                title: NSLocalizedString("Run the first sync", comment: "Setup title"),
                subtitle: NSLocalizedString("The first sync only adds and updates items, so you can check the result before deletions are synced.", comment: "Setup text")
            )
            if let plan = model.plan {
                let summary = PlanSummary(plan: plan)
                VStack(alignment: .leading, spacing: 6) {
                    if summary.isEmpty {
                        Label(NSLocalizedString("Everything is already in sync.", comment: "First sync summary"), systemImage: "checkmark.circle")
                    } else {
                        Text(NSLocalizedString("The first sync will:", comment: "First sync summary")).font(.headline)
                        ForEach(summary.lines, id: \.self) { line in
                            Label(line, systemImage: "circle.fill")
                                .labelStyle(BulletLabelStyle())
                        }
                    }
                    Label(NSLocalizedString("Nothing will be deleted on the first sync.", comment: "First sync summary"), systemImage: "checkmark.shield")
                        .foregroundColor(.green)
                        .padding(.top, 4)
                }
                if AppInfo.runsFromTemporaryLocation {
                    ErrorText(message: NSLocalizedString("Local Tasks Bridge is running from a temporary location. Quit, move it to your Applications folder, and open it again; otherwise it can’t start at login.", comment: "Setup warning"))
                }
                Button(NSLocalizedString("Start Syncing", comment: "Button")) { model.startSyncing() }
                    .controlSize(.large)
                    .keyboardShortcut(.defaultAction)
                    .disabled(model.working || AppInfo.runsFromTemporaryLocation)
            }
        }
    }
}

private struct BulletLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            configuration.icon.font(.system(size: 5)).foregroundColor(.secondary)
            configuration.title
        }
    }
}

private struct DoneStep: View {
    @ObservedObject var model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(
                title: NSLocalizedString("You’re all set", comment: "Setup title"),
                subtitle: NSLocalizedString("Local Tasks Bridge now syncs in the background and starts when you log in.", comment: "Setup text")
            )
            VStack(alignment: .leading, spacing: 10) {
                Label(NSLocalizedString("Find Local Tasks Bridge in the menu bar at the top of the screen.", comment: "Setup tip"), systemImage: MenuBarIconState.healthy.symbolName)
                Label(
                    String(format: NSLocalizedString("Choose Sync Now in its menu to sync right away. It also syncs every %@ and shortly after you change a reminder.", comment: "Setup tip; %@ is an interval such as “5 minutes”"), model.intervalDescription),
                    systemImage: "arrow.clockwise"
                )
                Label(NSLocalizedString("Open Settings from the menu to change lists, options, or the Google account.", comment: "Setup tip"), systemImage: "gearshape")
            }
            .fixedSize(horizontal: false, vertical: true)
            if let problem = model.loginItemProblem {
                ErrorText(message: String(format: NSLocalizedString("Start at login couldn’t be turned on: %@ You can turn it on in Settings > General.", comment: "Setup warning; %@ is the reason"), problem))
            }
            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    Text(NSLocalizedString("Command-line tool (optional)", comment: "Setup heading")).font(.headline)
                    Text(NSLocalizedString("Install the ltb command to check the status and sync from Terminal.", comment: "Setup text"))
                    Button(model.commandLineToolInstalled
                        ? NSLocalizedString("Reinstall Command-Line Tool", comment: "Button")
                        : NSLocalizedString("Install Command-Line Tool", comment: "Button")) {
                        model.installCommandLineTool()
                    }
                    if let message = model.commandLineToolMessage {
                        Text(message)
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(6)
            }
        }
    }
}
