import AppKit
import EventKit
import Foundation
import Darwin

final class BridgeDelegate: NSObject, NSApplicationDelegate {
    private let store = EKEventStore()
    private var child: Process?
    private var terminationSignal: DispatchSourceSignal?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // A named app owns the privacy grant instead of inheriting Codex access.
        store.requestFullAccessToReminders { [weak self] granted, error in
            DispatchQueue.main.async {
                guard granted else {
                    self?.fail("Local Tasks Bridge requires Reminders access. \(error?.localizedDescription ?? "Access denied.")")
                    return
                }
                self?.startSync()
            }
        }
    }

    private func fail(_ message: String) {
        FileHandle.standardError.write(Data((message + "\n").utf8))
        exit(1)
    }

    private func startSync() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let root = home.appendingPathComponent(".local/share/icloud-reminders-google-sync")
        let config = home.appendingPathComponent(".config/reminders-task-bridge-trial/daily-config.json")
        let process = Process()
        process.executableURL = root.appendingPathComponent("python-3.12/bin/python3.12")
        process.arguments = ["-B", "-u", root.appendingPathComponent("current/icloud_reminders_google_sync.py").path,
                             "--config", config.path, "run-loop"]
        process.currentDirectoryURL = root.appendingPathComponent("current")
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        environment["SDKROOT"] = "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"
        environment["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = environment
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError
        process.terminationHandler = { process in exit(process.terminationStatus) }
        do { try process.run() } catch { fail("Failed to launch local bridge: \(error.localizedDescription)") }
        child = process
        signal(SIGTERM, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        source.setEventHandler { [weak self] in
            guard let child = self?.child, child.isRunning else { exit(0) }
            child.terminate()
        }
        source.resume()
        terminationSignal = source
    }
}

@main
enum LocalBridgeLauncher {
    static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.accessory)
        let delegate = BridgeDelegate()
        application.delegate = delegate
        application.run()
        withExtendedLifetime(delegate) {}
    }
}
