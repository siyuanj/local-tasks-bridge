import SwiftUI

/// Recovery for `account_binding_required`: confirm the Apple and Google
/// accounts now in use, preview, then `rebuild --yes` builds a new sync map
/// with one safe sync. Nothing is deleted on either side.
@MainActor
final class RebuildModel: ObservableObject {
    let app: AppModel
    var close: () -> Void = {}

    @Published private(set) var checkingAccounts = false
    @Published private(set) var googleAccount: String?
    @Published private(set) var needsSignIn = false
    @Published private(set) var appleAccounts: [String] = []
    @Published private(set) var working = false
    /// `rebuild --yes` is running: it always finishes, so the sheet stays open.
    @Published private(set) var writing = false
    @Published private(set) var workingMessage: String?
    @Published private(set) var plan: SyncPlan?
    @Published private(set) var rebuilt = false
    @Published private(set) var errorMessage: String?

    private var task: Task<Void, Never>?

    init(app: AppModel) {
        self.app = app
    }

    var canPreview: Bool { !working && !checkingAccounts && googleAccount != nil }
    var canRebuild: Bool { canPreview && plan != nil && !rebuilt }
    var canSignInAgain: Bool { !working && !checkingAccounts && googleAccount != nil && !rebuilt }

    /// Reads the Google account (`account --json`) and the Reminders accounts (`lists --json`).
    func loadAccounts() {
        guard let client = app.client else {
            return
        }
        task?.cancel()
        checkingAccounts = true
        errorMessage = nil
        task = Task {
            do {
                let account = try await client.account()
                googleAccount = account.accountEmail ?? ""
                needsSignIn = false
            } catch let error as EngineError where error.code == EngineErrorCode.authRequired {
                googleAccount = nil
                needsSignIn = true
            } catch {
                show(error)
            }
            do {
                var titles: [String] = []
                for list in try await client.lists(includeGoogle: false).apple ?? [] {
                    let title = list.accountTitle ?? ""
                    if !title.isEmpty && !titles.contains(title) {
                        titles.append(title)
                    }
                }
                appleAccounts = titles
            } catch {
                show(error)
            }
            checkingAccounts = false
        }
    }

    func signIn() {
        perform(NSLocalizedString("Waiting for you to finish signing in in your browser…", comment: "Setup progress")) { client in
            _ = try await client.signIn()
            self.plan = nil
            self.loadAccounts()
        }
    }

    func preview() {
        perform(NSLocalizedString("Working out what the rebuild will do…", comment: "Rebuild progress")) { client in
            self.plan = try await client.rebuild(dryRun: true).plan ?? SyncPlan()
        }
    }

    func rebuild() {
        perform(NSLocalizedString("Rebuilding the sync map…", comment: "Rebuild progress"), writes: true) { client in
            _ = try await client.rebuild(dryRun: false)
            self.rebuilt = true
            _ = try? await self.app.currentStatus()
            try? await self.app.syncNow()
        }
    }

    func cancelWork() {
        if !writing {
            task?.cancel()
        }
    }

    private func perform(_ message: String, writes: Bool = false, _ work: @escaping (EngineClient) async throws -> Void) {
        guard let client = app.client, !writing else {
            return
        }
        task?.cancel()
        working = true
        writing = writes
        workingMessage = message
        errorMessage = nil
        task = Task {
            do {
                try await work(client)
            } catch {
                show(error)
            }
            working = false
            writing = false
            workingMessage = nil
        }
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
}

struct RebuildView: View {
    @ObservedObject var model: RebuildModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(NSLocalizedString("Pair Your Accounts Again", comment: "Rebuild title")).font(.title2).bold()
            Text(NSLocalizedString("The sync map on this Mac belongs to a different pair of Apple and Google accounts, so syncing stopped to keep your data safe. Rebuilding pairs the accounts below with one safe sync. Nothing is deleted on either side.", comment: "Rebuild explanation"))
                .fixedSize(horizontal: false, vertical: true)

            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    if model.checkingAccounts {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text(NSLocalizedString("Checking the accounts…", comment: "Rebuild progress")).foregroundColor(.secondary)
                        }
                    }
                    LabeledContent(NSLocalizedString("Google account", comment: "Rebuild row")) {
                        if let account = model.googleAccount {
                            Text(verbatim: account.isEmpty ? "—" : account)
                        } else if model.needsSignIn {
                            Button(NSLocalizedString("Sign In with Google", comment: "Button")) { model.signIn() }
                                .disabled(model.working)
                        } else {
                            Text(verbatim: "—")
                        }
                    }
                    LabeledContent(NSLocalizedString("Apple Reminders accounts", comment: "Rebuild row")) {
                        Text(model.appleAccounts.isEmpty
                            ? NSLocalizedString("None found", comment: "Rebuild row value")
                            : model.appleAccounts.joined(separator: ", "))
                    }
                    if model.canSignInAgain {
                        Button(NSLocalizedString("Use a Different Google Account", comment: "Button")) { model.signIn() }
                    }
                    if model.needsSignIn {
                        Text(NSLocalizedString("Sign in first so Local Tasks Bridge knows which Google account to pair.", comment: "Rebuild note"))
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(6)
            }

            if model.rebuilt {
                Label(NSLocalizedString("The sync map was rebuilt and syncing has resumed.", comment: "Rebuild result"), systemImage: "checkmark.circle.fill")
                    .foregroundColor(.green)
            } else if let plan = model.plan {
                PlanSummaryView(
                    plan: plan,
                    heading: NSLocalizedString("The rebuild will:", comment: "Rebuild summary"),
                    noDeletionNote: NSLocalizedString("Nothing will be deleted on either side.", comment: "Rebuild summary")
                )
            } else if model.canPreview {
                Text(NSLocalizedString("Preview the rebuild to see what it will add or update.", comment: "Rebuild note"))
                    .foregroundColor(.secondary)
            }
            if let message = model.errorMessage {
                ErrorText(message: message)
            }
            Spacer(minLength: 0)
            HStack {
                if model.working {
                    ProgressView().controlSize(.small)
                    if let message = model.workingMessage {
                        Text(message).foregroundColor(.secondary).lineLimit(2)
                    }
                }
                Spacer()
                if model.rebuilt {
                    Button(NSLocalizedString("Close", comment: "Button")) { model.close() }
                        .keyboardShortcut(.defaultAction)
                } else {
                    Button(NSLocalizedString("Cancel", comment: "Button")) {
                        model.cancelWork()
                        model.close()
                    }
                    .keyboardShortcut(.cancelAction)
                    .disabled(model.writing)
                    Button(NSLocalizedString("Preview", comment: "Button")) { model.preview() }
                        .disabled(!model.canPreview)
                    Button(NSLocalizedString("Rebuild", comment: "Button")) { model.rebuild() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(!model.canRebuild)
                }
            }
        }
        .padding(20)
        .frame(width: 520, height: 480)
        .interactiveDismissDisabled(model.writing)
        .onAppear { model.loadAccounts() }
    }
}
