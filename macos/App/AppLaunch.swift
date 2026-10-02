import AppKit

/// Command-line options of the app executable.
///
/// `--background` is passed by the login item. `--after-exit-of PID` and
/// `--show-settings` are used when the app restarts itself (see `Relauncher`).
struct LaunchOptions {
    var printVersion = false
    var background = false
    var waitForProcess: pid_t?
    var showSettings = false

    init(arguments: [String]) {
        var index = 1
        while index < arguments.count {
            switch arguments[index] {
            case "--version":
                printVersion = true
            case "--background":
                background = true
            case "--show-settings":
                showSettings = true
            case "--after-exit-of":
                if index + 1 < arguments.count, let pid = pid_t(arguments[index + 1]) {
                    waitForProcess = pid
                    index += 1
                }
            default:
                // LaunchServices and debuggers may add arguments of their own.
                break
            }
            index += 1
        }
    }
}

/// Keeps one running copy per user with an advisory lock in the user's
/// temporary directory. The lock disappears with the process, even after a crash.
enum InstanceGuard {
    private static var lockDescriptor: Int32 = -1

    static func acquire() -> Bool {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(AppInfo.bundleIdentifier).lock").path
        // O_CLOEXEC: an engine child that outlives the app must not keep the lock.
        let descriptor = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else {
            // Without a lock file, run rather than refuse to start.
            return true
        }
        if flock(descriptor, LOCK_EX | LOCK_NB) != 0 {
            close(descriptor)
            return false
        }
        lockDescriptor = descriptor
        return true
    }

    static func askRunningInstanceToShow() {
        DistributedNotificationCenter.default().postNotificationName(
            AppInfo.showRequestNotification,
            object: nil,
            userInfo: nil,
            deliverImmediately: true
        )
    }

    /// Waits for the copy that started this one to finish quitting.
    static func waitForExit(of pid: pid_t, timeout: TimeInterval) {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if kill(pid, 0) != 0 && errno == ESRCH {
                return
            }
            usleep(100_000)
        }
    }
}

/// Restarts the app (for example after the language changed): starts a new
/// copy through LaunchServices that waits for this one to exit, then quits.
enum Relauncher {
    @MainActor
    static func restart(showingSettings: Bool) {
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.createsNewApplicationInstance = true
        configuration.activates = true
        configuration.arguments = ["--after-exit-of", String(getpid())] + (showingSettings ? ["--show-settings"] : [])
        NSWorkspace.shared.openApplication(at: AppInfo.bundleURL, configuration: configuration) { _, error in
            DispatchQueue.main.async {
                if let error {
                    Alerts.show(error)
                } else {
                    NSApp.terminate(nil)
                }
            }
        }
    }
}
