import SwiftUI

/// Uninstall: stop syncing, run `uninstall`, move the app to the Trash, quit.
@MainActor
final class UninstallModel: ObservableObject {
    let app: AppModel
    var close: () -> Void = {}

    @Published var revokeGoogleAccess = true
    @Published var deleteLocalData = false
    @Published private(set) var working = false
    @Published private(set) var errorMessage: String?

    init(app: AppModel) {
        self.app = app
    }

    func uninstall() {
        guard let client = app.client else {
            return
        }
        working = true
        errorMessage = nil
        Task {
            // Stop the loop first so it cannot write new state while files go away.
            await app.suspendBackgroundWork()
            do {
                try await client.uninstall(revoke: revokeGoogleAccess, deleteData: deleteLocalData)
            } catch {
                errorMessage = (error as? EngineError)?.message ?? error.localizedDescription
                working = false
                await app.resumeBackgroundWork()
                return
            }
            CommandLineTool.removeIfInstalled(at: app.paths.commandLineToolLink)
            if deleteLocalData {
                UserDefaults.standard.removePersistentDomain(forName: AppInfo.bundleIdentifier)
            }
            app.log.write("uninstalled (revoke: \(revokeGoogleAccess), delete data: \(deleteLocalData))")
            moveToTrashAndQuit()
        }
    }

    private func moveToTrashAndQuit() {
        NSWorkspace.shared.recycle([AppInfo.bundleURL]) { _, error in
            DispatchQueue.main.async {
                if error != nil {
                    Alerts.inform(
                        title: NSLocalizedString("Local Tasks Bridge was uninstalled", comment: "Alert title"),
                        message: NSLocalizedString("It couldn’t move itself to the Trash. Drag Local Tasks Bridge from your Applications folder to the Trash.", comment: "Alert message")
                    )
                }
                // Exit status 0, so the login item's KeepAlive does not restart it.
                NSApp.terminate(nil)
            }
        }
    }
}

struct UninstallView: View {
    @ObservedObject var model: UninstallModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(NSLocalizedString("Uninstall Local Tasks Bridge", comment: "Window title")).font(.title2).bold()
            Text(NSLocalizedString("This stops syncing, removes the login item, and moves Local Tasks Bridge to the Trash. Your reminders and your Google tasks stay as they are.", comment: "Uninstall text"))
                .fixedSize(horizontal: false, vertical: true)
            Toggle(NSLocalizedString("Revoke Google access", comment: "Uninstall option"), isOn: $model.revokeGoogleAccess)
            VStack(alignment: .leading, spacing: 2) {
                Toggle(NSLocalizedString("Delete local data (settings, sync state, logs)", comment: "Uninstall option"), isOn: $model.deleteLocalData)
                Text(NSLocalizedString("Keep it if you may reinstall: signing in again then continues where you left off.", comment: "Uninstall option detail"))
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .padding(.leading, 20)
            }
            if let message = model.errorMessage {
                ErrorText(message: message)
            }
            Spacer(minLength: 0)
            HStack {
                if model.working {
                    ProgressView().controlSize(.small)
                    Text(NSLocalizedString("Uninstalling…", comment: "Uninstall progress"))
                        .foregroundColor(.secondary)
                }
                Spacer()
                Button(NSLocalizedString("Cancel", comment: "Button")) { model.close() }
                    .keyboardShortcut(.cancelAction)
                    .disabled(model.working)
                Button(NSLocalizedString("Uninstall", comment: "Button")) { model.uninstall() }
                    .disabled(model.working)
            }
        }
        .toggleStyle(.checkbox)
        .padding(20)
        .frame(width: 480, height: 300)
    }
}
