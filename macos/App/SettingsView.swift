import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        TabView(selection: $model.tab) {
            GeneralSettings(model: model)
                .tabItem { Label(NSLocalizedString("General", comment: "Settings tab"), systemImage: "gearshape") }
                .tag(SettingsModel.Tab.general)
            ListsSettings(model: model, lists: model.lists)
                .tabItem { Label(NSLocalizedString("Lists", comment: "Settings tab"), systemImage: "checklist") }
                .tag(SettingsModel.Tab.lists)
            SafetySettings(model: model)
                .tabItem { Label(NSLocalizedString("Safety", comment: "Settings tab"), systemImage: "checkmark.shield") }
                .tag(SettingsModel.Tab.safety)
            GoogleSettings(model: model, app: model.app)
                .tabItem { Label(NSLocalizedString("Google", comment: "Settings tab"), systemImage: "person.crop.circle") }
                .tag(SettingsModel.Tab.google)
            NetworkSettings(model: model)
                .tabItem { Label(NSLocalizedString("Network", comment: "Settings tab"), systemImage: "network") }
                .tag(SettingsModel.Tab.network)
            AdvancedSettings(model: model)
                .tabItem { Label(NSLocalizedString("Advanced", comment: "Settings tab"), systemImage: "wrench.and.screwdriver") }
                .tag(SettingsModel.Tab.advanced)
        }
        .padding(20)
        .frame(width: 660, height: 560)
        .task { await model.load() }
        .sheet(isPresented: Binding(
            get: { model.rebuildModel != nil },
            set: { shown in
                if !shown {
                    model.closeRebuild()
                }
            }
        )) {
            if let rebuild = model.rebuildModel {
                RebuildView(model: rebuild)
            }
        }
    }
}

/// Revert/Apply for tabs that keep a draft.
private struct ApplyBar: View {
    var changed: Bool
    var saving: Bool
    var canApply = true
    var revert: @MainActor () -> Void
    var apply: @MainActor () async -> Void

    var body: some View {
        HStack {
            if saving {
                ProgressView().controlSize(.small)
            }
            Spacer()
            Button(NSLocalizedString("Revert", comment: "Button"), action: revert)
                .disabled(!changed || saving)
            Button(NSLocalizedString("Apply", comment: "Button")) {
                Task { await apply() }
            }
            .keyboardShortcut(.defaultAction)
            .disabled(!changed || saving || !canApply)
        }
    }
}

private struct SettingsError: View {
    var message: String?

    var body: some View {
        if let message {
            ErrorText(message: message)
        }
    }
}

private struct GeneralSettings: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        Form {
            if model.configUnreadable {
                Section {
                    ErrorText(message: model.errorMessage ?? EngineError.fallbackMessage(for: EngineErrorCode.configInvalid))
                    Button(NSLocalizedString("Reset Settings…", comment: "Menu item")) {
                        Task { await model.resetSettings() }
                    }
                }
            }
            Section {
                Toggle(NSLocalizedString("Start at login", comment: "Setting"), isOn: Binding(
                    get: { model.startAtLogin },
                    set: { value in Task { await model.setStartAtLogin(value) } }
                ))
                .disabled(model.updatingLoginItem || (AppInfo.runsFromTemporaryLocation && !model.startAtLogin))
                if AppInfo.runsFromTemporaryLocation {
                    ErrorText(message: AppInfo.temporaryLocationMessage)
                }
                Text(NSLocalizedString("Local Tasks Bridge opens in the menu bar when you log in and keeps syncing in the background.", comment: "Setting detail"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Section {
                Picker(NSLocalizedString("Language", comment: "Setting"), selection: Binding(
                    get: { model.language },
                    set: { value in Task { await model.setLanguage(value) } }
                )) {
                    Text(NSLocalizedString("Automatic", comment: "Language option")).tag("auto")
                    Text(verbatim: "English").tag("en")
                    Text(verbatim: "简体中文").tag("zh")
                }
                if model.languageNeedsRestart {
                    HStack {
                        Text(NSLocalizedString("The new language is used after Local Tasks Bridge restarts.", comment: "Setting detail"))
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Spacer()
                        Button(NSLocalizedString("Restart Now", comment: "Button")) { model.restartApp() }
                    }
                }
            }
            Section {
                Toggle(NSLocalizedString("Show notifications", comment: "Setting"), isOn: Binding(
                    get: { model.notificationsOn },
                    set: { value in Task { await model.setNotifications(value) } }
                ))
                Text(NSLocalizedString("Tells you about sync problems and about changes that need your approval.", comment: "Setting detail"))
                    .font(.caption)
                    .foregroundColor(.secondary)
                if model.notificationsOn && model.notificationsDenied {
                    HStack {
                        Text(NSLocalizedString("Notifications for Local Tasks Bridge are turned off in System Settings.", comment: "Setting detail"))
                            .font(.caption)
                            .foregroundColor(.orange)
                        Spacer()
                        Button(NSLocalizedString("Open Notification Settings", comment: "Button")) { model.openNotificationSettings() }
                    }
                }
            }
            Section {
                IntervalPicker(seconds: Binding(
                    get: { model.interval },
                    set: { value in Task { await model.setInterval(value) } }
                ), sharedClient: model.clientStatus?.usesSharedClient ?? false)
            }
            SettingsError(message: model.errorMessage)
        }
        .formStyle(.grouped)
    }
}

private struct ListsSettings: View {
    @ObservedObject var model: SettingsModel
    @ObservedObject var lists: ListSelectionModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(NSLocalizedString("Each list you choose syncs with the Google Tasks list of the same name. Missing Google lists are created for you.", comment: "Setup text"))
                .foregroundColor(.secondary)
            ListPickerView(model: lists) {
                Task { await lists.load() }
            }
            HStack {
                Button(NSLocalizedString("Reload Lists", comment: "Button")) {
                    Task { await lists.load() }
                }
                .disabled(lists.loading)
                Spacer()
            }
            Divider()
            DirectionPicker(bidirectional: $model.bidirectional)
            SettingsError(message: model.errorMessage)
            Spacer(minLength: 0)
            ApplyBar(
                changed: model.listsChanged,
                saving: model.saving,
                canApply: !lists.selected.isEmpty,
                revert: model.revertLists,
                apply: model.saveLists
            )
        }
        .padding(16)
    }
}

private struct SafetySettings: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Form {
                Section {
                    Toggle(NSLocalizedString("Sync completions and deletions", comment: "Option"), isOn: $model.deleteStale)
                    Text(NSLocalizedString("When you complete or delete an item on one side, the same happens on the other side.", comment: "Setting detail"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Section(NSLocalizedString("Safety limit", comment: "Settings section")) {
                    Stepper(value: $model.maxChanges, in: 0...1000) {
                        Text(String(format: NSLocalizedString("Ask before more than %d items change at once", comment: "Setting; %d is a count"), model.maxChanges))
                    }
                    Stepper(value: $model.maxRatioPercent, in: 5...100, step: 5) {
                        Text(String(format: NSLocalizedString("…or more than %d%% of the synced items", comment: "Setting; %d is a percentage"), model.maxRatioPercent))
                    }
                    Text(NSLocalizedString("Above either limit, those deletions and completions wait for your approval in Review Pending Changes. Everything else keeps syncing.", comment: "Setting detail"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Section {
                    Picker(NSLocalizedString("When an item changed on both sides", comment: "Setting"), selection: $model.conflictPolicy) {
                        Text(NSLocalizedString("The newer change wins", comment: "Conflict policy")).tag("newer_wins")
                        Text(NSLocalizedString("Skip conflicting items", comment: "Conflict policy")).tag("skip")
                    }
                }
                SettingsError(message: model.errorMessage)
            }
            .formStyle(.grouped)
            ApplyBar(
                changed: model.safetyChanged,
                saving: model.saving,
                revert: model.revertSafety,
                apply: model.saveSafety
            )
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
        }
    }
}

private struct GoogleSettings: View {
    @ObservedObject var model: SettingsModel
    @ObservedObject var app: AppModel

    var body: some View {
        Form {
            if app.status?.condition == "account_binding_required" {
                Section {
                    ErrorText(message: NSLocalizedString("The Apple or Google account is different from the one this Mac synced with before.", comment: "Engine error"))
                    Button(NSLocalizedString("Pair Accounts Again…", comment: "Button")) { model.openRebuild() }
                }
            }
            Section(NSLocalizedString("Account", comment: "Settings section")) {
                if model.checkingAccount {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(NSLocalizedString("Checking your Google account…", comment: "Settings status"))
                            .foregroundColor(.secondary)
                    }
                } else if let email = model.accountEmail {
                    Label(String(format: NSLocalizedString("Signed in as %@", comment: "Setup status; %@ is an email address"), email), systemImage: "checkmark.circle.fill")
                        .foregroundColor(.green)
                } else if let problem = model.accountProblem {
                    ErrorText(message: problem)
                }
                if model.signingIn {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(NSLocalizedString("Waiting for you to finish signing in in your browser…", comment: "Setup progress"))
                            .foregroundColor(.secondary)
                        Spacer()
                        Button(NSLocalizedString("Cancel", comment: "Button")) { model.cancelSignIn() }
                    }
                } else {
                    HStack {
                        Button(NSLocalizedString("Reconnect Google", comment: "Button")) { model.reconnect() }
                        Button(NSLocalizedString("Sign Out…", comment: "Button")) {
                            Task { await model.signOut() }
                        }
                        .disabled(model.accountEmail == nil && model.accountProblem == nil)
                    }
                }
                if model.needsReconnect {
                    NoticeText(message: NSLocalizedString("Choose Reconnect Google to sign in with the new sign-in method.", comment: "Settings note"))
                }
            }
            Section(NSLocalizedString("Sign-in method", comment: "Settings section")) {
                if model.clientStatus?.bundledAvailable == true {
                    RadioOption(
                        title: NSLocalizedString("Quick sign-in (shared Local Tasks Bridge client)", comment: "Sign-in method"),
                        detail: NSLocalizedString("Up to 100 people share it and its daily Google quota.", comment: "Sign-in method detail"),
                        isSelected: model.clientStatus?.active == "bundled"
                    ) { Task { await model.chooseSharedClient(true) } }
                    RadioOption(
                        title: NSLocalizedString("My own Google Cloud OAuth client", comment: "Sign-in method"),
                        detail: model.clientStatus?.customReady == true
                            ? nil
                            : NSLocalizedString("Import a client JSON first.", comment: "Sign-in method detail"),
                        isSelected: model.clientStatus?.active == "custom"
                    ) { Task { await model.chooseSharedClient(false) } }
                    .disabled(model.clientStatus?.customReady != true)
                } else {
                    Text(model.clientStatus?.customReady == true
                        ? NSLocalizedString("Signs in with your own Google Cloud OAuth client.", comment: "Settings text")
                        : NSLocalizedString("No OAuth client is set up yet.", comment: "Settings text"))
                }
                HStack(spacing: 12) {
                    Button(NSLocalizedString("Import Client JSON…", comment: "Button")) { model.importClient() }
                    Link(NSLocalizedString("Step-by-step guide", comment: "Link"), destination: AppInfo.googleCloudSetupURL)
                }
                if let hint = model.importedClientHint {
                    Text(String(format: NSLocalizedString("Imported client %@", comment: "Setup status; %@ is a client ID hint"), hint))
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
            SettingsError(message: model.errorMessage)
        }
        .formStyle(.grouped)
        .task {
            if !model.signingIn {
                await model.checkAccount()
            }
        }
    }
}

private struct NetworkSettings: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(NSLocalizedString("How Local Tasks Bridge connects to Google", comment: "Settings text"))
                .font(.headline)
            ProxyEditor(choice: $model.proxy)
            SettingsError(message: model.errorMessage)
            Spacer(minLength: 0)
            ApplyBar(
                changed: model.networkChanged,
                saving: model.saving,
                canApply: model.proxy.isValid,
                revert: model.revertNetwork,
                apply: model.saveNetwork
            )
        }
        .padding(16)
    }
}

private struct AdvancedSettings: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        Form {
            Section(NSLocalizedString("Files", comment: "Settings section")) {
                LabeledContent(NSLocalizedString("Data folder", comment: "Setting")) {
                    Button(NSLocalizedString("Open Data Folder", comment: "Menu item")) { SystemActions.openDataFolder(paths: model.app.paths) }
                }
                LabeledContent(NSLocalizedString("Logs", comment: "Setting")) {
                    Button(NSLocalizedString("Open Logs", comment: "Menu item")) { SystemActions.openLogs(paths: model.app.paths) }
                }
                LabeledContent(NSLocalizedString("Diagnostics", comment: "Setting")) {
                    Button(NSLocalizedString("Copy Diagnostics", comment: "Menu item")) {
                        Task { await Diagnostics.copyToPasteboard(model: model.app) }
                    }
                }
            }
            Section(NSLocalizedString("Command-line tool", comment: "Settings section")) {
                LabeledContent(model.commandLineToolInstalled
                    ? NSLocalizedString("Installed at ~/.local/bin/ltb", comment: "Setting")
                    : NSLocalizedString("Not installed", comment: "Setting")) {
                    Button(model.commandLineToolInstalled
                        ? NSLocalizedString("Reinstall Command-Line Tool", comment: "Button")
                        : NSLocalizedString("Install Command-Line Tool", comment: "Button")) {
                        model.installCommandLineTool()
                    }
                    .disabled(AppInfo.runsFromTemporaryLocation)
                }
                if let message = model.commandLineToolMessage {
                    Text(message)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
            Section {
                LabeledContent(NSLocalizedString("Remove Local Tasks Bridge from this Mac", comment: "Setting")) {
                    Button(NSLocalizedString("Uninstall…", comment: "Button")) { model.showUninstall() }
                }
            }
        }
        .formStyle(.grouped)
    }
}
