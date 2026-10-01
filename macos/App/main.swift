import AppKit

// Writing to a pipe whose reader has exited must fail with EPIPE, not kill the app.
signal(SIGPIPE, SIG_IGN)

let launchOptions = LaunchOptions(arguments: CommandLine.arguments)

// `--version` must work without a window server (CI smoke test), so it is
// handled before AppKit starts.
if launchOptions.printVersion {
    print(AppInfo.version)
    exit(0)
}

if let previous = launchOptions.waitForProcess {
    InstanceGuard.waitForExit(of: previous, timeout: 45)
}

guard InstanceGuard.acquire() else {
    // A copy started at login stays quiet; one the person opened brings the
    // running copy forward instead.
    if !launchOptions.background {
        InstanceGuard.askRunningInstanceToShow()
    }
    exit(0)
}

let appPaths = AppPaths.current()
let appLog = AppLog(url: appPaths.appLog)
appLog.write("Local Tasks Bridge \(AppInfo.version) started" + (launchOptions.background ? " at login" : ""))

// Top-level code runs on the main thread; AppKit is driven from here.
MainActor.assumeIsolated {
    let application = NSApplication.shared
    let delegate = AppDelegate(options: launchOptions, paths: appPaths, log: appLog)
    application.delegate = delegate
    application.setActivationPolicy(.accessory)
    withExtendedLifetime(delegate) {
        application.run()
    }
}
